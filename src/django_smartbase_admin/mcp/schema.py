"""``list_admins`` discovery payload assembly.

Single public entry point: :func:`admin_entry`. Helpers below it are
grouped by what they describe (fields / inlines / actions).

Action schema helpers (row, detail, list, selection, inline) are
implemented in :mod:`django_smartbase_admin.mcp.actions` and imported
here so all action types are assembled in one place.
"""

from __future__ import annotations

import logging

from django.contrib.contenttypes.admin import GenericInlineModelAdmin

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
from django_smartbase_admin.mcp.actions import (
    action_entries_for,
    collect_action_entries,
)
from django_smartbase_admin.mcp.service import SBAdminMCPDetailService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field schema
# ---------------------------------------------------------------------------


def _filter_value_shape(widget) -> tuple[str, object] | None:
    """``(shape, example)`` for the widget's expected ``filter_data`` value.

    Agents otherwise have to guess between scalar / list / dict per
    widget kind — silent acceptance of the wrong shape (filter ignored,
    full table returned) makes that guessing dangerous. Reported here
    so the agent can pick the right shape on the first call.
    """
    if isinstance(widget, DateFilterWidget):
        return (
            "[start, end] — list of two ISO-8601 dates ('YYYY-MM-DD'); "
            "either side may be null for an open-ended range.",
            ["2026-06-01", "2026-06-30"],
        )
    if isinstance(widget, NumberRangeFilterWidget):
        return ("[min, max] — list of two numbers; either side may be null.", [0, 100])
    if isinstance(widget, BooleanFilterWidget):
        return ("bool", True)
    if isinstance(widget, MultipleChoiceFilterWidget):
        return ("list of choice values (strings)", [])
    if isinstance(widget, ChoiceFilterWidget):
        return ("single choice value (string)", "")
    if isinstance(widget, AutocompleteFilterWidget):
        return (
            "list of {'value': <pk>, 'label': <str>} entries — pks resolved via the autocomplete tool",
            [],
        )
    return ("string", "")


def _filter_info(field) -> dict | None:
    """Schema for the field's filter, or ``None`` if not filterable."""
    if getattr(field, "filter_disabled", False):
        return None
    widget = getattr(field, "filter_widget", None)
    if widget is None:
        return None

    info: dict = {
        "filter_field": getattr(field, "filter_field", None) or field.name,
        "widget": widget.__class__.__name__,
    }
    shape = _filter_value_shape(widget)
    if shape is not None:
        info["value_shape"], info["example"] = shape
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


def _field_entry(field) -> dict | None:
    filter_info = _filter_info(field)
    list_visible = bool(getattr(field, "list_visible", True))
    # Hidden columns with no filter are technical/supporting annotations —
    # not addressable via ``list_rows`` or ``filter_data``.
    if not list_visible and filter_info is None:
        return None
    entry: dict = {
        "name": field.name,
        "title": str(getattr(field, "title", None) or field.name),
        "list_visible": list_visible,
    }
    if filter_info is not None:
        entry["filter"] = filter_info
    return entry


# ---------------------------------------------------------------------------
# Inline schema
# ---------------------------------------------------------------------------


def _inline_join_kind(inline) -> str:
    """Broad join semantics — ``"fk"`` or ``"generic"``.

    ``"generic"`` means the inline uses a ``GenericForeignKey`` (content
    type + object id) rather than a plain FK — useful context for an
    agent reasoning about whether it can address inline rows by a simple
    pk or needs the parent's content type too.  Fake inlines are
    reported as ``"fk"`` because their batch-read contract is identical
    from the agent's perspective.

    Underlying column names (``fk_name``, ``ct_field``) are deliberately
    not exposed; the executor resolves the join server-side.
    """
    if isinstance(inline, GenericInlineModelAdmin):
        return "generic"
    return "fk"


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


def _inline_entry(inline, request) -> dict:
    # For fake inlines, ``inline.model`` is a dynamic proxy whose
    # auto-generated name is an internal detail. Report the original
    # model so agents see the real ``app.Model`` label.
    model_cls = getattr(inline, "original_model", None) or inline.model
    opts = model_cls._meta
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
        "join_kind": _inline_join_kind(inline),
        "fields": _inline_field_names(inline, request),
        "inline_actions": collect_action_entries(
            inline, "get_sbadmin_inline_list_actions_processed", request
        ),
    }
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
    """Per-fieldset actions, tagged with ``fieldset`` + ``invoke_with =
    "invoke_detail_action"`` so they merge cleanly into ``detail_actions``.
    """
    try:
        fieldsets = admin.get_sbadmin_fieldsets(request, None) or []
    except Exception:
        return []

    entries: list[dict] = []
    for fieldset, fieldset_data in fieldsets:
        try:
            actions = admin.get_sbadmin_fieldset_actions_processed(
                request, fieldset, fieldset_data, None
            )
        except Exception:
            logger.warning(
                "MCP schema: fieldset action collection failed on %s",
                admin.__class__.__name__,
                exc_info=True,
            )
            continue
        for action in actions or []:
            try:
                for entry in action_entries_for(action):
                    entry["invoke_with"] = "invoke_detail_action"
                    entry["fieldset"] = str(fieldset) if fieldset is not None else None
                    entries.append(entry)
            except Exception:
                logger.warning(
                    "MCP schema: skipping fieldset action on %s",
                    admin.__class__.__name__,
                    exc_info=True,
                )
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


def admin_entry(admin, request) -> dict:
    """Schema entry for one registered SBAdmin admin."""
    model = admin.model
    opts = model._meta

    try:
        fields = [
            entry
            for entry in (
                _field_entry(f) for f in admin.get_field_map(request).values()
            )
            if entry is not None
        ]
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

    return {
        "view_id": admin.get_id(),
        "app_label": opts.app_label,
        "model": opts.object_name,
        "verbose_name": str(opts.verbose_name),
        "verbose_name_plural": str(opts.verbose_name_plural),
        "fields": fields,
        "search_fields": list(admin.get_search_fields(request) or []),
        "detail_fields": _detail_field_entries(admin, request),
        "inlines": _inline_entries(admin, request),
        # --- actions (all four admin-level types) ---
        # row_actions:       per-row icon buttons on the list view.
        # detail_actions:    buttons on the change/detail form.
        # list_actions:      global top buttons above the list (no row context).
        # selection_actions: bulk buttons shown when rows are selected.
        # Processed getters run ``process_actions_permissions`` — same
        # filter the UI uses, so actions the caller can't invoke don't
        # appear in discovery (and the invoke path's permission gate has
        # nothing left to surprise the agent with).
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
