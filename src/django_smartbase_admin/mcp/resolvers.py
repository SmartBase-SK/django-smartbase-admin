"""Agent identifier (``view_id``, ...) -> SBAdmin object.

Each resolver raises a consistent, actionable exception so the MCP
transport surfaces a real reason rather than an empty payload:
``LookupError`` for "doesn't exist", ``TypeError`` for "wrong shape".
"""

from __future__ import annotations

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView


def resolve_admin(view_id: str, request=None) -> SBAdminBaseListView:
    """``view_id`` -> registered admin or inline.

    Resolves via the configuration's ``view_map`` when ``request`` is
    bridged (the same map ``delegate_to_action`` uses for dispatch) so
    inline view_ids return the instance that registered synthetic
    ``@sbadmin_action`` wrappers belong to. Falls back to walking
    ``sb_admin_site._registry`` for top-level admins when no request
    is provided.

    Permission checks intentionally happen later in
    ``init_view_dynamic`` and action guards, matching the normal SBAdmin
    URL dispatch path.
    """
    if request is not None:
        view_map = getattr(
            getattr(request, "request_data", None), "configuration", None
        )
        view_map = getattr(view_map, "view_map", None) or {}
        if view_id in view_map:
            return view_map[view_id]

    for admin in sb_admin_site._registry.values():
        if isinstance(admin, SBAdminBaseListView) and admin.get_id() == view_id:
            return admin
    raise LookupError(f"No SBAdmin view registered with view_id={view_id!r}.")
