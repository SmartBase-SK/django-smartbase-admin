"""``mcp_tool_called`` receiver — persists each call via ``SBAdminMCPLogService``.

Connected in this app's ``ready()``. Failures are swallowed and logged so a
logging error never propagates into (and breaks) the tool call.
"""

from __future__ import annotations

import logging

from django_smartbase_admin.mcp_log.services import SBAdminMCPLogService

logger = logging.getLogger(__name__)


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
    try:
        SBAdminMCPLogService.record(
            request=request,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_kwargs=tool_kwargs,
            result=result,
            error=error,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("Failed to record MCP request log for %s", tool_name)
