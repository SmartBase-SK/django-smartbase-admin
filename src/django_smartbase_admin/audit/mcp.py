"""Audit-log helpers exposed through the MCP layer.

Lives inside the audit package because it depends on
:class:`AdminAuditLog`. ``mcp/mcp.py`` calls in here only when
``django_smartbase_admin.audit`` is installed; the lazy import keeps
the MCP tool surface usable when the audit app is absent.
"""

from __future__ import annotations

import json

from django.contrib.contenttypes.models import ContentType

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.audit.models import AdminAuditLog
from django_smartbase_admin.engine.const import BASE_PARAMS_NAME, FILTER_DATA_NAME
from django_smartbase_admin.mcp.bridge import set_request_payload


def get_admin_history(
    admin,
    *,
    request,
    object_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Audit log entries for ``admin.model`` — optionally narrowed to one
    object — paginated and ordered newest-first.

    Delegates the actual querying to :class:`AdminAuditLogAdmin` via its
    own ``object_history`` / ``content_type`` list filters. That gets us
    the audit admin's own restrictions for free: non-superuser scoping,
    per-content-type ``restrict_queryset`` enforcement, and the OR clause
    over direct / parent / affected. We are *not* allowed to query
    ``AdminAuditLog.objects`` directly here — that bypasses the audit
    view's authorization.
    """
    audit_admin = sb_admin_site._registry.get(AdminAuditLog)
    if audit_admin is None:
        raise LookupError(
            "AdminAuditLogAdmin not registered on sb_admin_site; cannot "
            "expose audit history through MCP."
        )
    if not audit_admin.has_view_permission(request):
        raise PermissionError("No view permission on audit log.")

    ct = ContentType.objects.get_for_model(admin.model)
    if object_id is not None:
        # ``object_history`` filter expects a JSON-encoded autocomplete
        # value list (``[{"value": "ct_id:obj_id"}]``) — see
        # ``AutocompleteParseMixin.parse_value_from_input`` +
        # ``ObjectHistoryFilterWidget.parse_filter_value``. Triggers the
        # direct / parent / affected OR clause and skips the
        # non-superuser ``user=...`` narrowing.
        filter_data = {
            "object_history": json.dumps([{"value": f"{ct.id}:{object_id}"}])
        }
    else:
        # Model-wide: ``content_type`` filter restricts to that CT and
        # the audit admin's ``_apply_restricted_queryset_for_filters``
        # gates rows by the user's restricted queryset on that model.
        filter_data = {"content_type": json.dumps([{"value": str(ct.id)}])}

    base_params = {audit_admin.get_id(): {FILTER_DATA_NAME: filter_data}}
    set_request_payload(
        request,
        get={BASE_PARAMS_NAME: json.dumps(base_params)},
    )

    # ``get_queryset`` adds user-scoping + restricted-qs gates;
    # ``get_filter_from_request`` runs the field-level filter widgets
    # (``object_history`` / ``content_type``) — both are needed to mirror
    # what the audit list view does.
    action = audit_admin.sbadmin_list_action_class(audit_admin, request)
    qs = (
        audit_admin.get_queryset(request)
        .filter(action.get_filter_from_request())
        .order_by("-timestamp")
    )
    total = qs.count()
    offset = max(0, (page - 1) * page_size)
    rows = qs[offset : offset + page_size].select_related("user")

    return {
        "data": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "action_type": row.action_type,
                "user": getattr(row.user, "email", None)
                or (str(row.user) if row.user else None),
                "object_id": row.object_id,
                "object_repr": row.object_repr,
                "is_bulk": row.is_bulk,
                "bulk_count": row.bulk_count,
                "changes": row.changes,
                "source": row.source,
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "last_row": total,
    }
