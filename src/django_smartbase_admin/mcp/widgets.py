"""MCP schema helpers for SBAdmin dashboard/detail widgets."""

from __future__ import annotations

import logging
from typing import Any

from django_smartbase_admin.engine.dashboard import (
    SBAdminDashboardWidget,
    SBAdminDashboardListWidget,
)

logger = logging.getLogger(__name__)


def _widget_model_label(widget) -> str | None:
    model = getattr(widget, "model", None)
    if model is None:
        return None
    opts = model._meta
    return f"{opts.app_label}.{opts.object_name}"


def ensure_dashboard_widget(view) -> SBAdminDashboardWidget:
    if not isinstance(view, SBAdminDashboardWidget):
        raise LookupError(f"View {view.get_id()!r} is not a dashboard widget.")
    return view


def require_widget_parent_context(view, parent_object_id) -> None:
    """Require parent context for parent-mounted widgets without permission checks."""
    if isinstance(view, SBAdminDashboardWidget):
        if getattr(view, "parent_view", None) is not None and parent_object_id is None:
            raise ValueError(
                f"parent_object_id is required for widget {view.get_id()!r}."
            )
    elif parent_object_id is not None:
        ensure_dashboard_widget(view)


def widget_entry(
    widget,
    request,
    *,
    parent_view=None,
    parent_object_id: str | int | None = None,
) -> dict:
    """Return the MCP discovery payload for one rendered detail widget.

    Result shape::

        {
            "view_id": str,
            "name": str,
            "model": "app_label.ModelName",       # optional
            "parent_view_id": str,                 # optional
            "parent_object_id": str,               # optional
            "requires_parent_object_id": True,     # optional
            "data_tool": "list_rows" | "fetch_widget_data",
            # List widgets also include the keys from list_view_entry().
        }

    Common keys identify the widget view and optional parent object context.
    List widgets also advertise table fields/search/actions and must be read
    with ``list_rows``. Other dashboard widgets advertise ``fetch_widget_data``.
    """
    entry: dict[str, Any] = {
        "view_id": widget.get_id(),
        "name": str(getattr(widget, "name", None) or widget.get_id()),
    }
    model = _widget_model_label(widget)
    if model is not None:
        entry["model"] = model
    if parent_view is not None:
        entry["parent_view_id"] = parent_view.get_id()
    if parent_object_id is not None:
        entry["parent_object_id"] = str(parent_object_id)
        entry["requires_parent_object_id"] = True
    elif getattr(widget, "path_to_parent_instance_id", None) is not None:
        entry["requires_parent_object_id"] = True

    if isinstance(widget, SBAdminDashboardListWidget):
        from django_smartbase_admin.mcp.schema import list_view_entry

        entry.update(list_view_entry(widget, request))
        entry["data_tool"] = "list_rows"
    else:
        entry["data_tool"] = "fetch_widget_data"
    return entry


def _iter_layout_widgets(fieldset_layout) -> list:
    widgets = []
    for layout_item in fieldset_layout or ():
        widget = layout_item.get("widget")
        if widget is not None:
            widgets.append(widget)
        region_context = layout_item.get("region")
        if region_context is not None:
            widgets.extend(_iter_layout_widgets(region_context.fieldset_layout))
    return widgets


def detail_widget_entries(admin, request, adminform, obj) -> list[dict]:
    """Widgets rendered inside the current detail form layout.

    The browser gets these from ``form.get_fieldset_context()`` and renders
    ``layout_item["widget"]`` in place. MCP mirrors that exact source so
    dynamically-visible widgets and parent-specific widget ids match the UI.
    """
    form = getattr(adminform, "form", None)
    if form is None or not hasattr(form, "get_fieldset_context"):
        return []

    parent_object_id = getattr(obj, "pk", None)
    seen: set[str] = set()
    entries: list[dict] = []
    for fieldset in adminform:
        try:
            context = form.get_fieldset_context(fieldset, request) or {}
        except Exception:
            logger.warning(
                "MCP widgets: fieldset layout failed for %s on %s",
                getattr(fieldset, "name", None),
                admin.__class__.__name__,
                exc_info=True,
            )
            continue
        # ``admin.widgets`` only registers widget views. The fieldset layout is
        # the source of truth for widgets actually rendered on this detail page,
        # including widgets nested in dynamic regions.
        for widget in _iter_layout_widgets(context.get("fieldset_layout")):
            widget_id = widget.get_id()
            if widget_id in seen:
                continue
            seen.add(widget_id)
            try:
                widget.init_view_dynamic(request, request.request_data)
                if not widget.has_view_or_change_permission(request):
                    continue
                entries.append(
                    widget_entry(
                        widget,
                        request,
                        parent_view=admin,
                        parent_object_id=parent_object_id,
                    )
                )
            except Exception:
                logger.warning(
                    "MCP widgets: skipping widget %s on admin %s",
                    widget.__class__.__name__,
                    admin.__class__.__name__,
                    exc_info=True,
                )
    return entries
