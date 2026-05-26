"""Agent identifier (``view_id``, ...) -> SBAdmin object.

Each resolver raises a consistent, actionable exception so the MCP
transport surfaces a real reason rather than an empty payload:
``LookupError`` for "doesn't exist", ``TypeError`` for "wrong shape".
"""

from __future__ import annotations

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView


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
