"""Audit-log helpers exposed through the MCP layer.

Lives inside the audit package because it depends on
:class:`AdminAuditLog`. ``mcp/mcp.py`` calls in here only when
``django_smartbase_admin.audit`` is installed; the lazy import keeps
the MCP tool surface usable when the audit app is absent.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.models import Q

from django_smartbase_admin.audit.models import AdminAuditLog


def get_admin_history(
    admin, *, object_id: str | None = None, page: int = 1, page_size: int = 20
) -> dict:
    """Audit log entries for ``admin.model`` — optionally narrowed to one
    object — paginated and ordered newest-first.

    Mirrors the filter the "History" UI button builds via
    ``get_audit_history_url`` / ``get_audit_model_history_url``:
    direct changes (``content_type`` + optional ``object_id``), parent
    context (``parent_content_type`` + ``parent_object_id``), and JSON
    ``affected_objects`` membership.
    """
    ct = ContentType.objects.get_for_model(admin.model)
    ct_label = f"{ct.app_label}.{ct.model}"

    # ``affected_objects`` is a JSON field — ``__contains`` is Postgres-only.
    # Skip the JSON clause on backends without support so SQLite tests
    # (and other non-Postgres deployments) still work; the direct +
    # parent-context clauses cover the common cases.
    supports_json_contains = connection.features.supports_json_field_contains
    if object_id is not None:
        obj_str = str(object_id)
        filter_q = Q(content_type=ct, object_id=obj_str) | Q(
            parent_content_type=ct, parent_object_id=obj_str
        )
        if supports_json_contains:
            try:
                obj_pk_for_json = int(obj_str)
            except (TypeError, ValueError):
                obj_pk_for_json = obj_str
            filter_q |= Q(
                affected_objects__contains=[{"ct": ct_label, "id": obj_pk_for_json}]
            )
    else:
        filter_q = Q(content_type=ct) | Q(parent_content_type=ct)

    qs = AdminAuditLog.objects.filter(filter_q).order_by("-timestamp")
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
