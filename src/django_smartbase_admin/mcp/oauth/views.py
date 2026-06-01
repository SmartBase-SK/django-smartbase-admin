"""Discovery + Dynamic Client Registration views.

DOT 3.x ships authorize/token/revoke/introspect/OIDC, but **not** the two
endpoints MCP clients (Cursor, Claude Code) actually probe:

* ``/.well-known/oauth-authorization-server`` (RFC 8414)
* ``/.well-known/oauth-protected-resource``   (RFC 9728)

…and DOT does not ship an RFC 7591 DCR endpoint either. Both gaps are
filled here.

This module is **opt-in**. It is only loaded when the host project includes
``django_smartbase_admin.mcp.oauth.urls`` and adds ``oauth2_provider`` to
``INSTALLED_APPS``. Projects using a different ``BaseAuthentication`` for
the MCP endpoint (session, custom JWT, mTLS, …) do not need this module
at all — they just plug their auth class into
``DJANGO_MCP_AUTHENTICATION_CLASSES`` and skip the include.
"""

from __future__ import annotations

import json
import secrets

from django.http import HttpRequest, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from oauth2_provider.models import get_application_model

# Single scope granting full read-write access to the SBAdmin MCP tools.
# Tool-level authorization is the staff gate plus Django model permissions;
# the scope is not split read/write, so it must not imply read-only.
SUPPORTED_SCOPE = "sbadmin:write"


def _issuer(request: HttpRequest) -> str:
    return f"{request.scheme}://{request.get_host()}"


@require_GET
def authorization_server_metadata(request: HttpRequest) -> JsonResponse:
    """RFC 8414 metadata. Points clients at DOT's endpoints."""
    base = _issuer(request)
    return JsonResponse(
        {
            "issuer": base,
            "authorization_endpoint": base + reverse("oauth2_provider:authorize"),
            "token_endpoint": base + reverse("oauth2_provider:token"),
            "revocation_endpoint": base + reverse("oauth2_provider:revoke-token"),
            "introspection_endpoint": base + reverse("oauth2_provider:introspect"),
            "registration_endpoint": base + reverse("sbadmin_mcp_oauth_register"),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "scopes_supported": [SUPPORTED_SCOPE],
        }
    )


@require_GET
def protected_resource_metadata(request: HttpRequest) -> JsonResponse:
    """RFC 9728 metadata for the MCP resource server."""
    base = _issuer(request)
    return JsonResponse(
        {
            "resource": base + reverse("mcp_server_streamable_http_endpoint"),
            "authorization_servers": [base],
            "scopes_supported": [SUPPORTED_SCOPE],
            "bearer_methods_supported": ["header"],
        }
    )


@csrf_exempt
@require_POST
def register(request: HttpRequest) -> JsonResponse:
    """Minimal RFC 7591 DCR — provisions a DOT public client (PKCE-only)."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_client_metadata"}, status=400)

    redirect_uris = body.get("redirect_uris") or []
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return JsonResponse(
            {
                "error": "invalid_redirect_uri",
                "error_description": "redirect_uris is required",
            },
            status=400,
        )

    Application = get_application_model()
    app = Application(
        client_id=secrets.token_urlsafe(16),
        client_secret="",
        name=(body.get("client_name") or "MCP client")[:255],
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="\n".join(redirect_uris),
        skip_authorization=False,
        # Public clients use auth_method=none; PKCE is enforced by
        # OAUTH2_PROVIDER["PKCE_REQUIRED"].
    )
    # Public clients must not have a client_secret.
    app.client_secret = ""
    # Owner: the DCR endpoint is unauthenticated by design (MCP clients
    # self-register before any user is involved). Leave user=NULL.
    app.user = None
    app.save()

    return JsonResponse(
        {
            "client_id": app.client_id,
            "client_id_issued_at": int(app.created.timestamp()),
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "scope": SUPPORTED_SCOPE,
            "token_endpoint_auth_method": "none",
            "client_name": app.name,
        },
        status=201,
    )
