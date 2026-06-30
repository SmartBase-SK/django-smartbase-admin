"""MCP transport URLs.

Always-on MCP JSON-RPC endpoint provided by ``django-mcp-server``.
Authentication is selected by the host project via
``DJANGO_MCP_AUTHENTICATION_CLASSES`` (any DRF ``BaseAuthentication``
subclass).

The optional REST surface is intentionally narrow: only ``list_rows`` is
exposed, under the same URLconf, with acting-user resolution selected by
``SBADMIN_MCP_REST_AUTHENTICATOR``.

For the bundled OAuth 2.1 Authorization Server (Cursor / Claude / IDE
clients), additionally include ``django_smartbase_admin.mcp.oauth.urls``.
"""

from django.urls import include, path

from django_smartbase_admin.mcp.rest import SBAdminMCPToolAPIView

urlpatterns = [
    # MCP JSON-RPC endpoint. Path is controlled by ``DJANGO_MCP_ENDPOINT``
    # (default ``"mcp"``; we set ``"mcp/"`` so it matches our discovery
    # metadata's trailing slash).
    path("", include("mcp_server.urls")),
    path(
        "rest/tools/list_rows/",
        SBAdminMCPToolAPIView.as_view(),
        {"tool_name": "list_rows"},
        name="sbadmin_mcp_rest_tool",
    ),
]
