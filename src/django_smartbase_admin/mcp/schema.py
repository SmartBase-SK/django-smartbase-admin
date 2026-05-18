"""``list_admins`` discovery payload assembly.

Single public entry point: :func:`admin_entry`. Helpers below it are
grouped by what they describe (fields / inlines).
"""

from __future__ import annotations

import logging

from django.contrib.contenttypes.admin import GenericInlineModelAdmin

from django_smartbase_admin.engine.fake_inline import (
    SBAdminFakeInlineMixin,
    is_fake_inline_batch_safe,
)
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    ChoiceFilterWidget,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field schema
# ---------------------------------------------------------------------------


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
    if isinstance(widget, ChoiceFilterWidget) and widget.choices:
        # Boolean / Choice / MultipleChoice / RadioChoice all subclass this.
        info["choices"] = [
            {"value": value, "label": str(label)} for value, label in widget.choices
        ]
    if isinstance(widget, AutocompleteFilterWidget):
        info["multiselect"] = bool(widget.multiselect)
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
    """Join semantics only — ``fk`` / ``generic`` / ``fake``.

    Underlying ORM column names (``fk_name``, ``ct_field``,
    ``path_to_parent_instance_id``) are deliberately not exposed: the
    agent addresses inlines by their SBAdmin handle, the executor
    resolves the lookup server-side from its own catalog.
    """
    if isinstance(inline, GenericInlineModelAdmin):
        return "generic"
    if isinstance(inline, SBAdminFakeInlineMixin):
        return "fake"
    return "fk"


def _inline_field_names(inline, request) -> list[str]:
    """What ``InlineModelAdmin.get_fields`` would return for the change form.

    Pulls in ``get_form`` and its widget-init side effects — acceptable
    here, discovery doesn't need to be cheaper than rendering the form.
    """
    return [str(name) for name in inline.get_fields(request, None) or []]


def _inline_entry(inline, request) -> dict:
    opts = inline.model._meta
    return {
        "inline_name": inline.__class__.__name__,
        "model": f"{opts.app_label}.{opts.object_name}",
        "verbose_name": str(getattr(inline, "verbose_name", None) or opts.verbose_name),
        "verbose_name_plural": str(
            getattr(inline, "verbose_name_plural", None) or opts.verbose_name_plural
        ),
        "join_kind": _inline_join_kind(inline),
        "fields": _inline_field_names(inline, request),
    }


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
# Row actions
# ---------------------------------------------------------------------------


def _row_action_kind(action) -> str:
    if getattr(action, "target_view", None) is not None:
        return "modal"
    if getattr(action, "action_id", None):
        return "method"
    return "url"


def _row_action_entry(action) -> dict:
    entry: dict = {
        "title": str(getattr(action, "title", "") or ""),
        "kind": _row_action_kind(action),
    }
    action_id = getattr(action, "action_id", None)
    if action_id:
        entry["action_id"] = action_id
    target_view = getattr(action, "target_view", None)
    if target_view is not None:
        entry["target_view"] = target_view.__name__
    return entry


def _row_action_entries(admin, request) -> list[dict]:
    try:
        actions = admin.get_sbadmin_row_actions(request) or []
    except Exception:
        logger.warning(
            "MCP schema: get_sbadmin_row_actions failed for %s",
            admin.__class__.__name__,
            exc_info=True,
        )
        return []
    entries: list[dict] = []
    for action in actions:
        try:
            entries.append(_row_action_entry(action))
        except Exception:
            logger.warning(
                "MCP schema: skipping row action on %s",
                admin.__class__.__name__,
                exc_info=True,
            )
    return entries


# ---------------------------------------------------------------------------
# Top-level admin schema
# ---------------------------------------------------------------------------


def admin_entry(admin, request) -> dict:
    """Schema entry for one registered SBAdmin admin."""
    model = admin.model
    opts = model._meta
    concrete = opts.concrete_model

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
        "admin_name": admin.__class__.__name__,
        "view_id": admin.get_id(),
        "app_label": opts.app_label,
        "model": opts.object_name,
        "base_model": concrete._meta.object_name,
        "is_proxy": opts.proxy,
        "verbose_name": str(opts.verbose_name),
        "verbose_name_plural": str(opts.verbose_name_plural),
        "fields": fields,
        "search_fields": list(admin.get_search_fields(request) or []),
        "inlines": _inline_entries(admin, request),
        "row_actions": _row_action_entries(admin, request),
    }
