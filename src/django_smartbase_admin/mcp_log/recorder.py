"""``mcp_tool_called`` receiver that writes one ``MCPRequestLog`` per call.

Connected in this app's ``ready()``. Failures are swallowed and logged.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

ERROR_MESSAGE_LIMIT = 2000

# Result keys whose list value counts as "items returned".
_ITEM_KEYS = ("data", "rows", "results", "items", "admin_views", "choices")
# Result keys carrying a total/row count.
_TOTAL_KEYS = ("total", "count", "recordsTotal", "recordsFiltered")


def _enabled() -> bool:
    return getattr(settings, "SB_ADMIN_MCP_REQUEST_LOG_ENABLED", True)


def _dumps(value) -> str:
    """Best-effort JSON; ``default=str`` covers Decimals, dates, models."""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return repr(value)


def _build_payload(args: tuple, kwargs: dict) -> tuple[dict, int]:
    """Return ``(full_request_payload, byte_size)`` for the call's inputs."""
    payload: dict = dict(kwargs)
    if args:
        payload["__positional__"] = list(args)

    text = _dumps(payload)
    size = len(text.encode("utf-8"))
    try:
        payload = json.loads(text)
    except ValueError:
        payload = {"_unserializable": True, "_repr": text}
    return payload, size


def _summarize_result(result) -> dict:
    """Light response metadata (counts/shape) as model field values."""
    meta = {
        "result_status": "",
        "result_count": None,
        "result_total": None,
        "result_fields": None,
        "result_inlines": None,
        "result_inline_rows": None,
    }
    if isinstance(result, list):
        meta["result_count"] = len(result)
        return meta
    if not isinstance(result, dict):
        return meta

    if isinstance(result.get("status"), str):
        meta["result_status"] = result["status"][:32]
    for key in _ITEM_KEYS:
        if isinstance(result.get(key), list):
            meta["result_count"] = len(result[key])
            break
    for key in _TOTAL_KEYS:
        if isinstance(result.get(key), int):
            meta["result_total"] = result[key]
            break
    if isinstance(result.get("fields"), dict):
        meta["result_fields"] = len(result["fields"])
    if isinstance(result.get("inlines"), dict):
        inlines = result["inlines"]
        meta["result_inlines"] = len(inlines)
        meta["result_inline_rows"] = sum(
            len(v["rows"])
            for v in inlines.values()
            if isinstance(v, dict) and isinstance(v.get("rows"), list)
        )
    return meta


def on_mcp_tool_called(
    sender,
    request=None,
    tool_name="",
    tool_args=(),
    tool_kwargs=None,
    result=None,
    error=None,
    duration_ms=0,
    **extra,
) -> None:
    if not _enabled():
        return
    try:
        from django_smartbase_admin.mcp_log.models import MCPRequestLog

        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None

        payload, request_size = _build_payload(tool_args or (), tool_kwargs or {})

        response_size = 0
        response_meta = _summarize_result(None)
        if result is not None:
            response_size = len(_dumps(result).encode("utf-8"))
            response_meta = _summarize_result(result)

        error_type = ""
        error_message = ""
        if error is not None:
            error_type = type(error).__name__
            error_message = str(error)[:ERROR_MESSAGE_LIMIT]

        MCPRequestLog.objects.create(
            user=user,
            tool_name=tool_name,
            arguments=payload,
            request_size=request_size,
            response_size=response_size,
            duration_ms=duration_ms,
            is_error=error is not None,
            error_type=error_type,
            error_message=error_message,
            **response_meta,
        )
    except Exception:
        logger.exception("Failed to record MCP request log for %s", tool_name)
