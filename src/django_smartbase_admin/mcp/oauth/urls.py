"""Bundled OAuth 2.1 Authorization Server URLs (django-oauth-toolkit).

**Opt-in.** Include this from your project's URLconf only if you want to
use the bundled DOT-backed Authorization Server for the MCP endpoint:

    # settings.py
    INSTALLED_APPS = [..., "oauth2_provider", ...]
    DJANGO_MCP_AUTHENTICATION_CLASSES = [
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    ]

    # urls.py — must be mounted BEFORE any catch-all
    urlpatterns = [
        path("", include("django_smartbase_admin.mcp.urls")),
        path("", include("django_smartbase_admin.mcp.oauth.urls")),
        ...
    ]

If you authenticate MCP requests differently (session cookie, custom JWT,
mTLS, IAP header, …), do **not** include this module — point
``DJANGO_MCP_AUTHENTICATION_CLASSES`` at your own ``BaseAuthentication``
subclass instead. The MCP endpoint itself stays the same.

No ``app_name`` is set: ``oauth2_provider.urls`` declares its own
``app_name`` and we want ``reverse("oauth2_provider:authorize")`` to
keep working. Reverse our own routes by their explicit ``name="..."``
(e.g. ``reverse("sbadmin_mcp_oauth_register")``).
"""

from django.urls import include, path

from django_smartbase_admin.mcp.oauth import views

urlpatterns = [
    # MCP-required discovery endpoints (DOT does not ship these).
    path(
        ".well-known/oauth-authorization-server",
        views.authorization_server_metadata,
        name="sbadmin_mcp_oauth_metadata",
    ),
    path(
        ".well-known/oauth-protected-resource",
        views.protected_resource_metadata,
        name="sbadmin_mcp_oauth_resource_metadata",
    ),
    # Minimal RFC 7591 Dynamic Client Registration.
    path("oauth/register", views.register, name="sbadmin_mcp_oauth_register"),
    # authorize/token/revoke/introspect/OIDC live in DOT.
    path("o/", include("oauth2_provider.urls", namespace="oauth2_provider")),
]
