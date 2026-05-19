"""Combined MCP + bundled OAuth URLconf used by the MCP smoke tests.

Mirrors what a production project would wire when it opts into the
bundled OAuth 2.1 Authorization Server.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("django_smartbase_admin.mcp.urls")),
    path("", include("django_smartbase_admin.mcp.oauth.urls")),
]
