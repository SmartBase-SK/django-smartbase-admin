"""``list_admins`` discovery payload assembly.

Single public entry point: :func:`admin_entry`. Helpers below it are
grouped by what they describe (fields / inlines / actions).

Action schema helpers (row, detail, list, selection, inline) are
implemented in :mod:`django_smartbase_admin.mcp.actions` and imported
here so all action types are assembled in one place.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django_smartbase_admin.engine.const import ROW_CLASS_FIELD
from django_smartbase_admin.engine.fake_inline import is_fake_inline_batch_safe
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    BooleanFilterWidget,
    ChoiceFilterWidget,
    DateFilterWidget,
    MultipleChoiceFilterWidget,
    NumberRangeFilterWidget,
)
from django_smartbase_admin.mcp.actions import collect_action_entries
from django_smartbase_admin.mcp.service import SBAdminMCPDetailService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field schema
# ---------------------------------------------------------------------------


# Filter widgets form a small fixed taxonomy from the agent's
# perspective — each base class defines one ``filter_data`` shape and the
# subclasses only swap UI / datasource concerns. Reporting that base
# category (not the concrete subclass) on each field lets us publish the
# shape contract once, in the ``widget_shapes`` legend, instead of
# copying ``value_shape`` / ``example`` onto every field.
#
# Order matters: ``MultipleChoiceFilterWidget`` subclasses
# ``ChoiceFilterWidget``, so it must be checked first.
_WIDGET_CATEGORIES: tuple[tuple[type, str], ...] = (
    (DateFilterWidget, "DateFilterWidget"),
    (NumberRangeFilterWidget, "NumberRangeFilterWidget"),
    (BooleanFilterWidget, "BooleanFilterWidget"),
    (MultipleChoiceFilterWidget, "MultipleChoiceFilterWidget"),
    (ChoiceFilterWidget, "ChoiceFilterWidget"),
    (AutocompleteFilterWidget, "AutocompleteFilterWidget"),
)

WIDGET_SHAPES: dict[str, dict] = {
    "DateFilterWidget": {
        "value_shape": (
            "[start, end] — list of two ISO-8601 dates ('YYYY-MM-DD'); "
            "either side may be null for an open-ended range."
        ),
        "example": ["2026-06-01", "2026-06-30"],
    },
    "NumberRangeFilterWidget": {
        "value_shape": (
            "{'from': {'value': <number>}, 'to': {'value': <number>}} — "
            "either side may be omitted for an open-ended range "
            "(e.g. {'from': {'value': 10}} means >= 10, "
            "{'to': {'value': 10}} means <= 10)."
        ),
        "example": {"from": {"value": 0}, "to": {"value": 100}},
    },
    "BooleanFilterWidget": {"value_shape": "bool", "example": True},
    "MultipleChoiceFilterWidget": {
        "value_shape": (
            "list of choice values from fields[].filter.choices "
            "(bool, string, or number) — never a bare scalar; "
            "e.g. [false] not false"
        ),
        "example": [False],
    },
    "ChoiceFilterWidget": {
        "value_shape": "single choice value (string)",
        "example": "",
    },
    "AutocompleteFilterWidget": {
        "value_shape": (
            "list of {'value': <pk>, 'label': <str>} entries — "
            "pks resolved via the autocomplete tool"
        ),
        "example": [],
    },
    "StringFilterWidget": {"value_shape": "string (substring match)", "example": ""},
}


def get_widget_shapes() -> dict[str, dict]:
    """Built-in ``WIDGET_SHAPES`` plus any project-declared additions.

    Projects with custom filter widgets can document their ``filter_data``
    shape by setting ``SBADMIN_MCP_ADDITIONAL_WIDGET_SHAPES`` (same
    ``{name: {"value_shape", "example"}}`` form) — entries are merged on
    top of the built-ins, so a project can also override a built-in shape.
    Resolved per request so ``override_settings`` and runtime changes take
    effect.
    """
    additional = getattr(settings, "SBADMIN_MCP_ADDITIONAL_WIDGET_SHAPES", None) or {}
    return {**WIDGET_SHAPES, **additional}


def _widget_category(widget) -> str:
    """Base widget category for the legend lookup.

    Subclasses of the known bases (e.g. ``FromValuesAutocompleteWidget``,
    ad-hoc per-admin ``_*FilterWidget`` classes) collapse to the base —
    they don't change the ``filter_data`` shape, only datasource / UI.
    """
    for base, name in _WIDGET_CATEGORIES:
        if isinstance(widget, base):
            return name
    return "StringFilterWidget"


def _filter_info(field) -> dict | None:
    """Schema for the field's filter, or ``None`` if not filterable."""
    if getattr(field, "filter_disabled", False):
        return None
    widget = getattr(field, "filter_widget", None)
    if widget is None:
        return None

    # The filter is keyed by the column ``name`` in list_rows filter_data
    # (the same identifier ``fields`` / ``sort`` use), so the internal
    # ``filter_field`` is deliberately not surfaced — one filter identifier,
    # not two. list_rows still *accepts* a raw ``filter_field`` key (presets
    # emit those), but the agent never needs to construct one.
    info: dict = {
        "widget": _widget_category(widget),
    }
    if isinstance(widget, ChoiceFilterWidget) and widget.choices:
        # Boolean / Choice / MultipleChoice / RadioChoice all subclass this.
        info["choices"] = [
            {"value": value, "label": str(label)} for value, label in widget.choices
        ]
    if isinstance(widget, AutocompleteFilterWidget):
        info["multiselect"] = bool(widget.multiselect)
        info["widget_id"] = widget.get_id()
        target = getattr(widget, "model", None)
        if target is not None:
            opts = target._meta
            info["target_model"] = f"{opts.app_label}.{opts.object_name}"
    return info


def _field_entry(field) -> dict:
    filter_info = _filter_info(field)
    entry: dict = {
        "name": field.name,
        "title": str(getattr(field, "title", None) or field.name),
    }
    # Default is ``true``; emit only when hidden so the field still
    # surfaces in discovery (callers may need to know hidden-but-real
    # columns exist) without paying the per-field flag cost on the >80 %
    # majority that are visible.
    if not getattr(field, "list_visible", True):
        entry["list_visible"] = False
    if filter_info is not None:
        entry["filter"] = filter_info
    return entry


# ---------------------------------------------------------------------------
# Inline schema
# ---------------------------------------------------------------------------


def _inline_field_names(inline, request) -> list[str]:
    """What ``InlineModelAdmin.get_fields`` would return for the change form.

    Pulls in ``get_form`` and its widget-init side effects — acceptable
    here, discovery doesn't need to be cheaper than rendering the form.

    ``ROW_CLASS_FIELD`` is a UI-only CSS hook injected by every
    ``SBAdminInline``; it is stripped here just as the detail service
    strips it from inline row payloads.
    """
    return [
        str(name)
        for name in inline.get_fields(request, None) or []
        if name != ROW_CLASS_FIELD
    ]


def _inline_relation_targets(model_cls, field_names) -> dict:
    """``{field: "app.Model"}`` for the inline's relational columns.

    Inline rows carry FK / M2M columns as bare pks (``{"work": 443}``).
    Emitted once per inline (not per row), this map tells the agent the
    target model behind each such id — enough to interpret it and to pick
    the right model to ``autocomplete`` against when resolving a *name* to
    an id. Reverse resolution (id -> label) for a single object is done by
    ``fetch_detail``, which labels inline FKs the same way it does parent
    FKs; ``autocomplete`` is forward-only and can't do it.
    """
    targets: dict[str, str] = {}
    for name in field_names:
        try:
            field = model_cls._meta.get_field(name)
        except Exception:
            continue
        related = getattr(field, "related_model", None)
        if related is not None:
            opts = related._meta
            targets[name] = f"{opts.app_label}.{opts.object_name}"
    return targets


def _inline_entry(inline, request) -> dict:
    # For fake inlines, ``inline.model`` is a dynamic proxy whose
    # auto-generated name is an internal detail. Report the original
    # model so agents see the real ``app.Model`` label.
    model_cls = getattr(inline, "original_model", None) or inline.model
    opts = model_cls._meta
    field_names = _inline_field_names(inline, request)
    entry = {
        "inline_name": inline.__class__.__name__,
        # Inlines are registered in ``view_map`` under their own
        # ``get_id()``; agents pass this as ``view_id`` to
        # ``invoke_inline_action`` (object_id refers to an inline row,
        # dispatched via the inline's queryset).
        "view_id": inline.get_id(),
        "model": f"{opts.app_label}.{opts.object_name}",
        "verbose_name": str(getattr(inline, "verbose_name", None) or opts.verbose_name),
        "verbose_name_plural": str(
            getattr(inline, "verbose_name_plural", None) or opts.verbose_name_plural
        ),
        "fields": field_names,
    }
    # Per-inline FK/M2M -> target model map (once, not per row) so bare
    # inline ids in ``list_rows(include_inlines)`` are interpretable.
    relations = _inline_relation_targets(model_cls, field_names)
    if relations:
        entry["relations"] = relations
    inline_actions = collect_action_entries(
        inline, "get_sbadmin_inline_list_actions_processed", request
    )
    if inline_actions:
        entry["inline_actions"] = inline_actions
    return entry


def _inline_entries(admin, request) -> list[dict]:
    """Real + fake inlines the user can view; broken inlines are skipped."""
    inline_classes = list(admin.get_inlines(request, None) or [])
    inline_classes.extend(admin.get_sbadmin_fake_inlines(request, obj=None) or [])

    entries: list[dict] = []
    for inline_class in inline_classes:
        try:
            if not is_fake_inline_batch_safe(inline_class):
                # Asymmetric override on the fake-inline filter hooks — batch
                # read would diverge from the change form, so hide from MCP.
                # ``sbadmin.W004`` surfaces the same issue at deploy time.
                continue
            inline = inline_class(admin.model, admin.admin_site)
            if not inline.has_view_or_change_permission(request, None):
                continue
            entries.append(_inline_entry(inline, request))
        except Exception:
            logger.warning(
                "MCP schema: skipping inline %s on admin %s",
                inline_class.__name__,
                admin.__class__.__name__,
                exc_info=True,
            )
            continue
    return entries


# ---------------------------------------------------------------------------
# Detail fields
# ---------------------------------------------------------------------------


def _fieldset_action_entries(admin, request) -> list[dict]:
    """Per-fieldset actions, tagged with ``fieldset`` so they merge
    cleanly into ``detail_actions`` (invoked via ``invoke_detail_action``
    per the top-level ``action_invokers`` legend).
    """
    try:
        fieldsets = admin.get_sbadmin_fieldsets(request, None) or []
    except Exception:
        return []

    entries: list[dict] = []
    for fieldset, fieldset_data in fieldsets:
        for entry in collect_action_entries(
            admin,
            "get_sbadmin_fieldset_actions_processed",
            request,
            fieldset=fieldset,
            fieldset_data=fieldset_data,
            object_id=None,
        ):
            entry["fieldset"] = str(fieldset) if fieldset is not None else None
            entries.append(entry)
    return entries


def _detail_field_entries(admin, request) -> list[str]:
    """Detail-page field handles, in display order.

    Schema-side stays intentionally minimal — names only — so
    discovery doesn't have to construct a form. Per-field metadata
    (readonly flag, widget class) is reported by ``fetch_detail``
    itself, sourced from the live render so we have one source of
    truth instead of two.
    """
    try:
        names = list(
            SBAdminMCPDetailService.get_detail_fields(admin, request, None) or []
        )
    except ImproperlyConfigured:
        # List-only admin with no detail page — no fieldsets by design.
        # Mirrors how get_form autocomplete registration treats this case.
        return []
    except Exception:
        logger.warning(
            "MCP schema: get_detail_fields failed for %s",
            admin.__class__.__name__,
            exc_info=True,
        )
        return []
    return [str(name) for name in names]


# Row / detail / list / selection / inline actions are all handled by
# django_smartbase_admin.mcp.actions — imported at the top of this module.


# ---------------------------------------------------------------------------
# Top-level admin schema
# ---------------------------------------------------------------------------


def _filter_preset_entries(admin, request) -> list[dict]:
    """Static + saved filter presets available to the user, in display order.

    Static presets are admin-defined named bundles of url_params
    (``sbadmin_list_view_config`` + the implicit ``"All"`` reset). Saved
    presets are per-user rows in ``SBAdminListViewConfiguration``. Both
    are surfaced as ``{name, source, id?}``; the filter/sort params
    themselves are fetched on demand via ``fetch_filter_preset`` so this
    discovery payload stays small even when admins ship many presets.

    Errors in either source are swallowed (logged) so a broken preset
    config can't take down ``list_admins`` — the agent still sees the
    rest of the admin.
    """
    from django_smartbase_admin.services.configuration import (  # local import: avoids settings touch at module load
        SBAdminUserConfigurationService,
    )

    entries: list[dict] = []
    try:
        # ``get_base_config`` returns ``{name, url_params, ...}`` for the
        # built-in "All" reset plus every entry in ``sbadmin_list_view_config``.
        for preset in admin.get_base_config(request) or []:
            entries.append({"name": str(preset.get("name", "")), "source": "static"})
    except Exception:
        logger.warning(
            "MCP schema: static preset collection failed on %s",
            admin.__class__.__name__,
            exc_info=True,
        )
    try:
        saved = SBAdminUserConfigurationService.get_saved_views(
            request, view_id=admin.get_id()
        )
    except Exception:
        logger.warning(
            "MCP schema: saved preset collection failed on %s",
            admin.__class__.__name__,
            exc_info=True,
        )
        saved = []
    for preset in saved or []:
        entry = {"name": str(preset.get("name", "")), "source": "saved"}
        # ``id`` is the only stable handle for saved presets (the name is
        # user-editable) — surface it so ``fetch_filter_preset`` resolves by pk.
        if preset.get("id") is not None:
            entry["id"] = preset["id"]
        entries.append(entry)
    return entries


def admin_entry(admin, request) -> dict:
    """Schema entry for one registered SBAdmin admin."""
    model = admin.model
    opts = model._meta

    try:
        fields = [_field_entry(f) for f in admin.get_field_map(request).values()]
    except Exception:
        # Surface the admin even if field init trips — at least the
        # agent learns it exists.
        logger.warning(
            "MCP schema: field init failed for admin %s; "
            "falling back to bare name list",
            admin.__class__.__name__,
            exc_info=True,
        )
        fields = [
            {"name": getattr(f, "name", str(f))}
            for f in admin.get_sbadmin_list_display(request)
        ]

    entry: dict = {
        "view_id": admin.get_id(),
        "app_label": opts.app_label,
        "model": opts.object_name,
        "verbose_name": str(opts.verbose_name),
        "verbose_name_plural": str(opts.verbose_name_plural),
        "fields": fields,
        "search_fields": list(admin.get_search_fields(request) or []),
        "detail_fields": _detail_field_entries(admin, request),
        "inlines": _inline_entries(admin, request),
        "filter_presets": _filter_preset_entries(admin, request),
    }
    if admin.mcp_description:
        entry["description"] = str(admin.mcp_description)
    # --- actions (all four admin-level types) ---
    # row_actions:       per-row icon buttons on the list view.
    # detail_actions:    buttons on the change/detail form.
    # list_actions:      global top buttons above the list (no row context).
    # selection_actions: bulk buttons shown when rows are selected.
    # Processed getters run ``process_actions_permissions`` — same
    # filter the UI uses, so actions the caller can't invoke don't
    # appear in discovery (and the invoke path's permission gate has
    # nothing left to surprise the agent with). Empty action arrays are
    # omitted to keep the discovery payload compact.
    action_groups = {
        "row_actions": collect_action_entries(
            admin, "get_sbadmin_row_actions_processed", request
        ),
        "detail_actions": [
            *collect_action_entries(
                admin, "get_sbadmin_detail_actions_processed", request
            ),
            *_fieldset_action_entries(admin, request),
        ],
        "list_actions": collect_action_entries(
            admin, "get_sbadmin_list_actions_processed", request
        ),
        "selection_actions": collect_action_entries(
            admin, "get_sbadmin_list_selection_actions_processed", request
        ),
    }
    for key, value in action_groups.items():
        if value:
            entry[key] = value
    return entry
