"""Agent identifier (``view_id``, field name, ...) -> SBAdmin object.

Each resolver raises a consistent, actionable exception so the MCP
transport surfaces a real reason rather than an empty payload:
``LookupError`` for "doesn't exist", ``TypeError`` for "wrong shape".
"""

from __future__ import annotations

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget


def resolve_admin(view_id: str) -> SBAdminBaseListView:
    """``view_id`` -> registered admin.

    Permission checks intentionally happen later in ``init_view_dynamic``
    and action guards, matching the normal SBAdmin URL dispatch path.
    """
    for admin in sb_admin_site._registry.values():
        if not isinstance(admin, SBAdminBaseListView):
            continue
        if admin.get_id() != view_id:
            continue
        return admin
    raise LookupError(f"No SBAdmin admin registered with view_id={view_id!r}.")


def resolve_filter_widget(admin, request, field_name: str) -> AutocompleteFilterWidget:
    """``field_name`` on ``admin`` -> autocomplete filter widget.

    Pulls the widget from ``get_field_map`` (i.e. the per-request
    initialized clone) — that's the one with ``view``/``view_id`` wired
    and registered in ``configuration.autocomplete_map``, which is what
    ``action_autocomplete`` looks up by ``widget.get_id()``. The raw
    ``SBAdminField`` declarations never go through
    ``init_filter_widget_static``.
    """
    field = admin.get_field_map(request).get(field_name)
    if field is None:
        raise LookupError(
            f"No SBAdminField named {field_name!r} on view_id={admin.get_id()!r}."
        )
    widget = getattr(field, "filter_widget", None)
    if widget is None:
        raise LookupError(
            f"Field {field_name!r} on {admin.get_id()!r} has no filter widget."
        )
    if not isinstance(widget, AutocompleteFilterWidget):
        raise TypeError(
            f"Field {field_name!r} on {admin.get_id()!r} uses "
            f"{widget.__class__.__name__}, which is not an autocomplete "
            "filter widget."
        )
    return widget
