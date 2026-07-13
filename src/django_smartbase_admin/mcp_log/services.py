"""Builds and persists one ``MCPRequestLog`` row from an MCP tool call.

``SBAdminMCPLogService.record`` is the entry point — the ``logger`` signal
receiver delegates to it. Secret-named arguments are redacted; the response is
reduced to light metadata (counts/shape), never stored as a body.
"""

from __future__ import annotations

import json

from django.conf import settings


class SBAdminMCPLogService:
    REDACTED = "***"
    ERROR_MESSAGE_LIMIT = 2000

    # Substrings that mark a payload key as secret; its value is replaced with
    # ``REDACTED``. Extend via ``SB_ADMIN_MCP_REQUEST_LOG_SENSITIVE_KEYS``.
    SENSITIVE_KEY_PARTS = (
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "auth",
        "private_key",
        "access_key",
        "credential",
        "card_number",
        "cvv",
        "pin",
    )

    # Result keys whose list value counts as "items returned".
    ITEM_KEYS = ("data", "rows", "results", "items", "admin_views", "choices")
    # Result keys carrying a total/row count.
    TOTAL_KEYS = ("total", "count", "recordsTotal", "recordsFiltered")

    @classmethod
    def enabled(cls) -> bool:
        return getattr(settings, "SB_ADMIN_MCP_REQUEST_LOG_ENABLED", True)

    @classmethod
    def record(
        cls,
        *,
        request,
        tool_name,
        tool_args,
        tool_kwargs,
        result,
        error,
        duration_ms,
    ) -> None:
        """Create one ``MCPRequestLog`` row for a dispatched tool call."""
        if not cls.enabled():
            return
        from django_smartbase_admin.mcp_log.models import MCPRequestLog

        user = getattr(request, "user", None)
        if user is not None and not getattr(user, "is_authenticated", False):
            user = None

        kwargs = tool_kwargs or {}
        payload, request_size = cls._build_payload(tool_args or (), kwargs)

        response_size = 0
        response_meta = cls._summarize_result(None, kwargs)
        if result is not None:
            response_size = len(cls._dumps(result).encode("utf-8"))
            response_meta = cls._summarize_result(result, kwargs)

        error_type = ""
        error_message = ""
        if error is not None:
            error_type = type(error).__name__
            error_message = str(error)[: cls.ERROR_MESSAGE_LIMIT]

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

    # ── helpers ──────────────────────────────────────────────────────────

    @classmethod
    def _redact_enabled(cls) -> bool:
        return getattr(settings, "SB_ADMIN_MCP_REQUEST_LOG_REDACT", True)

    @classmethod
    def _sensitive_parts(cls) -> tuple:
        extra = getattr(settings, "SB_ADMIN_MCP_REQUEST_LOG_SENSITIVE_KEYS", ()) or ()
        return cls.SENSITIVE_KEY_PARTS + tuple(str(k).lower() for k in extra)

    @classmethod
    def _redact(cls, value, parts):
        """Recursively replace values of secret-named keys with ``REDACTED``."""
        if isinstance(value, dict):
            out = {}
            for key, val in value.items():
                if isinstance(key, str) and any(p in key.lower() for p in parts):
                    out[key] = cls.REDACTED
                else:
                    out[key] = cls._redact(val, parts)
            return out
        if isinstance(value, list):
            return [cls._redact(item, parts) for item in value]
        return value

    @staticmethod
    def _dumps(value) -> str:
        """Best-effort JSON; ``default=str`` covers Decimals, dates, models."""
        try:
            return json.dumps(value, default=str, ensure_ascii=False)
        except Exception:
            return repr(value)

    @classmethod
    def _build_payload(cls, args: tuple, kwargs: dict) -> tuple[dict, int]:
        """Return ``(stored_request_payload, byte_size)`` for the call's inputs.

        Secret-named keys are redacted before storage (disable via
        ``SB_ADMIN_MCP_REQUEST_LOG_REDACT = False``). ``byte_size`` reflects the
        real input volume (measured before redaction)."""
        payload: dict = dict(kwargs)
        if args:
            payload["__positional__"] = list(args)

        text = cls._dumps(payload)
        size = len(text.encode("utf-8"))
        try:
            payload = json.loads(text)
        except ValueError:
            return {"_unserializable": True, "_repr": cls.REDACTED}, size
        if cls._redact_enabled():
            payload = cls._redact(payload, cls._sensitive_parts())
        return payload, size

    @classmethod
    def _summarize_result(cls, result, kwargs) -> dict:
        """Light response metadata as model field values.

        ``result_total`` is the one count per call: total matching for lists
        (falling back to items returned), 1 for single-object reads/writes, or
        the affected count for bulk/delete.
        """
        meta = {
            "result_status": "",
            "result_total": None,
            "result_fields": None,
            "result_inlines": None,
            "result_inline_rows": None,
        }
        if isinstance(result, list):
            meta["result_total"] = len(result)
        elif isinstance(result, dict):
            if isinstance(result.get("status"), str):
                meta["result_status"] = result["status"][:32]
            # Prefer an explicit total (list pagination / action-reported
            # count), else fall back to the number of items in this response.
            for key in cls.TOTAL_KEYS:
                if isinstance(result.get(key), int):
                    meta["result_total"] = result[key]
                    break
            if meta["result_total"] is None and isinstance(result.get("data"), dict):
                if isinstance(result["data"].get("count"), int):
                    meta["result_total"] = result["data"]["count"]
            if meta["result_total"] is None:
                for key in cls.ITEM_KEYS:
                    if isinstance(result.get(key), list):
                        meta["result_total"] = len(result[key])
                        break
            if isinstance(result.get("components"), dict):
                components = result["components"]
                main = components.get("main", {})
                if isinstance(main.get("fields"), dict):
                    meta["result_fields"] = len(main["fields"])
                formsets = [
                    component
                    for component in components.values()
                    if isinstance(component, dict)
                    and component.get("type") == "formset"
                ]
                meta["result_inlines"] = len(formsets)
                meta["result_inline_rows"] = sum(
                    len(component["rows"])
                    for component in formsets
                    if isinstance(component.get("rows"), list)
                )
            # Single-object tools (update_detail / create_object / fetch_detail)
            # return one object keyed by ``id``.
            if meta["result_total"] is None and result.get("id") is not None:
                meta["result_total"] = 1

        # Bulk tools (invoke_selection_action / delete_objects) carry the
        # affected set explicitly as ``object_ids``.
        if meta["result_total"] is None and isinstance(kwargs.get("object_ids"), list):
            meta["result_total"] = len(kwargs["object_ids"])
        # Single-object actions (invoke_row/detail/inline_action) act on one
        # ``object_id`` even when their response carries no ``id``.
        elif meta["result_total"] is None and kwargs.get("object_id"):
            meta["result_total"] = 1
        return meta
