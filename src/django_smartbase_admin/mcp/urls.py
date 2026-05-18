"""MCP transport URLs.

Always-on, auth-agnostic surface: just the MCP JSON-RPC endpoint provided
by ``django-mcp-server``. Authentication is selected by the host project
via ``DJANGO_MCP_AUTHENTICATION_CLASSES`` (any DRF ``BaseAuthentication``
subclass).

For the bundled OAuth 2.1 Authorization Server (Cursor / Claude / IDE
clients), additionally include ``django_smartbase_admin.mcp.oauth.urls``.
"""

from django.urls import include, path


urlpatterns = [
    # MCP JSON-RPC endpoint. Path is controlled by ``DJANGO_MCP_ENDPOINT``
    # (default ``"mcp"``; we set ``"mcp/"`` so it matches our discovery
    # metadata's trailing slash).
    path("", include("mcp_server.urls")),
]
