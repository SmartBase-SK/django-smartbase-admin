"""MCP transport <-> SBAdmin pipeline bridging."""

from __future__ import annotations

import numbers

from django.http import HttpRequest, QueryDict
from django.utils.datastructures import MultiValueDict
from rest_framework.request import Request as DRFRequest

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


def unwrap_drf_request(request) -> HttpRequest | None:
    """Normalize the transport request to SBAdmin's Django request contract."""
    if request is None:
        return None
    if isinstance(request, DRFRequest):
        django_request = request._request
        django_request.user = request.user

        # The MCP server may attach these directly to the DRF wrapper instead
        # of its underlying Django request.
        for attribute in ("session", "request_data", "LANGUAGE_CODE", "_messages"):
            if attribute in request.__dict__:
                setattr(django_request, attribute, request.__dict__[attribute])
        return django_request
    if not isinstance(request, HttpRequest):
        raise TypeError("SBAdmin MCP tools require a Django HttpRequest.")
    return request


def ensure_sbadmin_request_data(request: HttpRequest) -> None:
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

    # Tag the request so the audit manager can stamp ``source="mcp"`` on
    # any AdminAuditLog row produced during this call — including manual
    # ``create_audit_log`` calls inside MCP-triggered queue/row actions.
    request._sbadmin_audit_source = "mcp"

    # Flag the request as MCP so the formatter pipeline can bypass
    # locale-dependent built-ins (date / datetime / boolean) and emit
    # one canonical wire format. Lives on ``request`` (not
    # ``request_data``) so it survives the request_data rebuild
    # ``delegate_to_action`` does via ``from_request_and_kwargs``.
    request.is_mcp = True

    # Always bind the contextvar — test fixtures pre-attach
    # ``request_data`` but don't bind the thread-local, and the audit
    # manager keys ``_is_in_admin_context`` off the contextvar.
    SBAdminThreadLocalService.set_request(request)

    if getattr(request, "request_data", None) is not None:
        return

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


def bind_sbadmin_request_data(
    request,
    *,
    view=None,
    action=None,
    modifier=None,
    object_id=None,
    method=None,
    get=None,
    post=None,
) -> SBAdminViewRequestData:
    """Bind MCP request context through SBAdmin's normal URL-request shape."""
    set_request_payload(request, get=get, post=post, method=method)
    return SBAdminViewRequestData.from_request_and_kwargs(
        request,
        view=view,
        action=action,
        modifier=modifier,
        object_id=object_id,
    )


def _to_querydict(mapping: dict) -> QueryDict:
    """Build a ``QueryDict`` from a flat ``{str: scalar}`` mapping.

    Stringifies scalars defensively: this builds the GET/POST surface
    consumed by the wsgi-shaped list pipeline (filters, search,
    autocomplete), where downstream parsers assume string values. The
    write path in :mod:`service` constructs its own ``QueryDict`` of
    native Python that ``Field.to_python`` accepts directly — that
    contract is independent of this helper.
    """
    qd = QueryDict(mutable=True)
    for key, value in mapping.items():
        qd[key] = value if isinstance(value, str) else str(value)
    return qd


def build_columns_data(admin, request, fields: list[str], field_map=None) -> dict:
    """Translate an MCP ``fields`` selection into the list action's
    ``columnsData`` payload: validates against the admin's field map and
    marks the requested subset visible.

    ``field_map`` lets the caller reuse an already-built map instead of
    rebuilding it (``get_field_map`` clones every field on each call).
    """
    if not isinstance(fields, list) or not fields:
        raise TypeError("list_rows requires a non-empty 'fields' list.")

    if field_map is None:
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


def set_request_post(
    request: HttpRequest,
    post_qd: QueryDict,
    files: MultiValueDict | None = None,
) -> None:
    """Replace the synthetic Django request's form payload."""
    if not isinstance(request, HttpRequest):
        raise TypeError("SBAdmin request payload requires a Django HttpRequest.")
    if files is None:
        files = MultiValueDict()
    request.POST = post_qd
    request._files = files
    request.META["CONTENT_TYPE"] = "application/x-www-form-urlencoded"


def set_request_payload(
    request: HttpRequest, *, get=None, post=None, method=None
) -> None:
    """Mirror tool-supplied params onto both ``request_data`` and ``request``.

    SBAdmin actions read from ``request.request_data.request_get`` /
    ``.request_post`` / ``.request_method`` — the canonical pipeline
    channel. We also mirror onto the Django request so permissions,
    middleware, and admin code that touch ``request.GET`` / ``POST`` /
    ``method`` see the same values.
    """
    rd = request.request_data

    if get is not None:
        rd.request_get = get
        request.GET = _to_querydict(get)
    if post is not None:
        rd.request_post = post
        if isinstance(post, QueryDict):
            set_request_post(request, post)
        else:
            set_request_post(request, _to_querydict(post))
    if method is not None:
        rd.request_method = method
        request.method = method


_MESSAGE_LEVEL_NAMES = {
    10: "debug",
    20: "info",
    25: "success",
    30: "warning",
    40: "error",
}


class MCPMessageStorage:
    """Capturing ``request._messages`` backend for the MCP request lifecycle.

    Views in the SBAdmin pipeline emit user-facing info via Django's
    ``messages`` framework — success notices ("Formula created"), warnings
    ("No selection made"), counts, etc. The browser surfaces them via the
    messages middleware; MCP has no equivalent rendering, but the
    information is just as useful to an agent. This storage collects each
    ``messages.<level>(request, ...)`` call so the response normalizer
    can include them in the JSON payload.
    """

    def __init__(self):
        self.messages: list[dict] = []

    def add(self, level, message, extra_tags=""):
        entry = {
            "level": _MESSAGE_LEVEL_NAMES.get(int(level), str(level)),
            "message": str(message),
        }
        if extra_tags:
            entry["tags"] = extra_tags
        self.messages.append(entry)

    def update(self, response):
        # No-op — messages are captured, not handed off to a cookie or
        # session backend.
        pass

    def __iter__(self):
        return iter(self.messages)


def ensure_messages_storage(request) -> None:
    """Attach an ``MCPMessageStorage`` if no messages backend is bound.

    Idempotent — re-uses an existing capturing storage if already set so
    a single request can accumulate messages across multiple action
    dispatches.
    """
    if not isinstance(getattr(request, "_messages", None), MCPMessageStorage):
        request._messages = MCPMessageStorage()


def captured_messages(request) -> list[dict]:
    """Return messages captured during this request, or ``[]`` if storage
    isn't an :class:`MCPMessageStorage` (so callers can call this
    unconditionally without checking)."""
    storage = getattr(request, "_messages", None)
    if isinstance(storage, MCPMessageStorage):
        return list(storage.messages)
    return []


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
