"""MCP tool registration.

``django-mcp-server`` autodiscovers ``<app>.mcp`` modules at startup
(see ``mcp_server.apps.McpServerConfig.ready``). Tool registration uses
either the FastMCP-style ``@mcp_server.tool()`` decorator or the
class-based ``MCPToolset`` / ``ModelQueryToolset``.

Phase 1 ships a single ``hello`` tool to verify OAuth + JSON-RPC. Real
read-only SBAdmin surface (``list_models``, ``get``, ``search``,
``aggregate``, ``related_rows``) gets added with ``ModelQueryToolset``
subclasses next to each app's models.
"""

from __future__ import annotations

from mcp_server import MCPToolset


class HelloTools(MCPToolset):
    """Smoke-test tools for verifying MCP transport + OAuth."""

    def hello(self, name: str = "world") -> str:
        """Say hello — verifies MCP auth + transport are wired correctly."""
        return f"Hello, {name}!"
