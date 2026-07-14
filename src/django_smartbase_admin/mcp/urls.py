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

from django.conf import settings
from django.urls import include, path

from django_smartbase_admin.mcp.rest import SBAdminMCPToolAPIView

_mcp_endpoint = getattr(settings, "DJANGO_MCP_ENDPOINT", "mcp")
_mcp_endpoint = _mcp_endpoint.strip("/")
_rest_list_rows_path = (
    f"{_mcp_endpoint}/rest/tools/list_rows/"
    if _mcp_endpoint
    else "rest/tools/list_rows/"
)

urlpatterns = [
    # Delegate the complete transport wiring to django-mcp-server. Keep
    # DJANGO_MCP_ENDPOINT slashless: remote clients such as Claude canonicalize
    # the MCP resource to /mcp and do not replay the POST across a 301.
    path("", include("mcp_server.urls")),
    path(
        _rest_list_rows_path,
        SBAdminMCPToolAPIView.as_view(),
        {"tool_name": "list_rows"},
        name="sbadmin_mcp_rest_tool",
    ),
]
