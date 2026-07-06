"""Signals emitted by the MCP tool layer.

``mcp_tool_called`` fires once per dispatched tool. Receiver kwargs:
    request, tool_name, tool_args, tool_kwargs, result, error, duration_ms
"""

import django.dispatch

mcp_tool_called = django.dispatch.Signal()
