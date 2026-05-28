"""MCP-spec-compliant DRF authentication class.

The MCP authorization spec (and RFC 9728) require that an unauthenticated
request to the resource server (the MCP endpoint) gets back a 401 with
a ``WWW-Authenticate: Bearer resource_metadata="..."`` header pointing
at the protected-resource metadata document. Clients (Cursor, Claude,
Cowork) use that header to discover the authorization server and kick
off the OAuth flow.

``oauth2_provider``'s default ``OAuth2Authentication.authenticate_header``
returns ``Bearer realm="api"`` — missing ``resource_metadata`` — so the
client has no way to discover OAuth and falls back to refusing to
install. This subclass adds the parameter.

Wire it in via ``DJANGO_MCP_AUTHENTICATION_CLASSES``:

    DJANGO_MCP_AUTHENTICATION_CLASSES = [
        "django_smartbase_admin.mcp.oauth.auth.SBAdminMCPOAuth2Authentication",
    ]
"""

from __future__ import annotations

from django.urls import reverse
from oauth2_provider.contrib.rest_framework import OAuth2Authentication


class SBAdminMCPOAuth2Authentication(OAuth2Authentication):
    def authenticate_header(self, request) -> str:
        resource_metadata = request.build_absolute_uri(
            reverse("sbadmin_mcp_oauth_resource_metadata")
        )
        base = super().authenticate_header(request)
        return f'{base}, resource_metadata="{resource_metadata}"'
