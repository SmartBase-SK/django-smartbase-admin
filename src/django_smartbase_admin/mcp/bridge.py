"""DRF/MCP request <-> SBAdmin pipeline bridging."""

from __future__ import annotations

import numbers

from django.http import QueryDict

from django_smartbase_admin.engine.const import (
    COLUMNS_DATA_COLUMNS_NAME,
    COLUMNS_DATA_VISIBLE_NAME,
    Formatter,
)
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.configuration import (
    SBAdminConfigurationService,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.xlsx_export import strip_html_cell_value


def ensure_sbadmin_request_data(request) -> None:
    """Attach ``request.request_data`` lazily so SBAdmin internals work.

    No-op if already set (test fixtures, pre-bridged requests). MCP
    tools never go through SBAdmin's URL middleware, so without this
    the first ``has_*_permission`` / ``restrict_queryset`` call crashes.

    Also stubs ``request.session`` when missing so
    ``SBAdminViewRequestData.from_request_and_kwargs`` (reached via
    ``delegate_to_action``) doesn't crash on its ``request.session.get(...)``
    call — MCP transport never runs ``SessionMiddleware``.
    """
    if not hasattr(request, "session"):
        request.session = {}

    if getattr(request, "request_data", None) is not None:
        return

    SBAdminThreadLocalService.set_request(request)

    request_data = SBAdminViewRequestData(
        view=None,
        action=None,
        modifier=None,
        user=request.user,
        request_meta=getattr(request, "META", {}) or {},
        request_get=getattr(request, "GET", {}) or {},
        request_post=getattr(request, "POST", {}) or {},
        request_method=getattr(request, "method", "GET"),
        global_filter=None,
        session=getattr(request, "session", {}) or {},
    )
    request_data.configuration = SBAdminConfigurationService.get_configuration(
        request_data
    )
    request.request_data = request_data


def _to_querydict(mapping: dict) -> QueryDict:
    """Build a ``QueryDict`` from a flat ``{str: scalar}`` mapping.

    ``QueryDict`` only stores strings — callers pass either already-encoded
    JSON or simple scalars, but coerce defensively so a stray ``int`` /
    ``bool`` doesn't reach the wsgi-shaped ``request.GET`` / ``POST``
    consumers downstream.
    """
    qd = QueryDict(mutable=True)
    for key, value in mapping.items():
        qd[key] = value if isinstance(value, str) else str(value)
    return qd


def build_columns_data(admin, request, fields: list[str]) -> dict:
    """Translate an MCP ``fields`` selection into the list action's
    ``columnsData`` payload: validates against the admin's field map and
    marks the requested subset visible.
    """
    if not isinstance(fields, list) or not fields:
        raise TypeError("list_rows requires a non-empty 'fields' list.")

    field_map = admin.get_field_map(request)
    unknown = [name for name in fields if name not in field_map]
    if unknown:
        raise LookupError(
            f"Admin {admin.get_id()!r} has no fields {unknown}; "
            f"available: {sorted(field_map)}."
        )

    requested = set(fields)
    return {
        COLUMNS_DATA_COLUMNS_NAME: {
            field.field: {COLUMNS_DATA_VISIBLE_NAME: name in requested}
            for name, field in field_map.items()
        }
    }


def set_request_payload(request, *, get=None, post=None, method=None) -> None:
    """Mirror tool-supplied params onto both ``request_data`` and ``request``.

    SBAdmin actions read from ``request.request_data.request_get`` /
    ``.request_post`` / ``.request_method``; we keep ``request.GET`` /
    ``.POST`` / ``.method`` in sync for code that reaches for the raw
    ``HttpRequest``.
    """
    rd = request.request_data
    if get is not None:
        rd.request_get = get
        request.GET = _to_querydict(get)
    if post is not None:
        rd.request_post = post
        request.POST = _to_querydict(post)
    if method is not None:
        rd.request_method = method
        request.method = method


def strip_html_cells(admin, request, rows: list[dict]) -> None:
    """Plain-text the ``Formatter.HTML`` cells in-place. Numbers / bools pass
    through; same classification the xlsx exporter uses."""
    html_keys = {
        field.field
        for field in admin.get_field_map(request).values()
        if getattr(field, "formatter", None) == Formatter.HTML.value
    }
    if not html_keys:
        return
    for row in rows:
        for key in html_keys:
            value = row.get(key)
            if value is None or isinstance(value, (bool, numbers.Number)):
                continue
            row[key] = strip_html_cell_value(value)
