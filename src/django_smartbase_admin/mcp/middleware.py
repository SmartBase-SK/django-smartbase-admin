"""CORS middleware for MCP + OAuth endpoints.

Browser-hosted MCP clients (claude.ai's Cowork integration, the various
ChatGPT bridges, Cursor's web client) and custom browser dashboards
cross-origin POST to ``/mcp/`` and send an OAuth preflight to
``/.well-known/oauth-protected-resource``. Without
``Access-Control-Allow-Origin`` + matching ``-Methods`` / ``-Headers``,
the browser blocks every request before it reaches Django.

This middleware adds the required headers on the MCP endpoint plus the
OAuth discovery / registration / authorization paths, gated by an
explicit origin allowlist set via ``SBADMIN_MCP_ALLOWED_ORIGINS``.

Default allowlist covers Claude (``https://claude.ai``) and Cursor
(``https://cursor.com``) so their install flows work out of the box.
Override to expand or lock down further. CORS is applied only to MCP /
OAuth paths so unrelated views are untouched.

Wire it in via ``MIDDLEWARE`` *before* anything that returns 401/403
on the MCP path so the preflight short-circuit fires first:

    MIDDLEWARE = [
        "django_smartbase_admin.mcp.middleware.SBAdminMCPCorsMiddleware",
        ...
    ]
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse

DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "https://claude.ai",
    "https://cursor.com",
)

# Paths the middleware decorates. Kept inline rather than reverse()'d
# because middleware runs on every request — a startup-time URL resolver
# walk would just trade configuration for an import-order hazard.
_MCP_PATH_PREFIXES: tuple[str, ...] = (
    "/mcp",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/oauth/",
    "/o/",
)

# Headers MCP clients legitimately send. ``MCP-Protocol-Version`` and
# ``MCP-Session-Id`` are part of the streamable HTTP transport spec.
_ALLOWED_REQUEST_HEADERS = (
    "Authorization, Content-Type, MCP-Protocol-Version, MCP-Session-Id"
)
# ``WWW-Authenticate`` carries the ``resource_metadata`` pointer the
# client needs to read across origins to start the OAuth flow.
_EXPOSED_RESPONSE_HEADERS = "WWW-Authenticate, MCP-Session-Id"
_ALLOWED_METHODS = "GET, POST, DELETE, OPTIONS"


def _allowed_origins() -> frozenset[str]:
    return frozenset(
        getattr(settings, "SBADMIN_MCP_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    )


def _path_is_mcp(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _MCP_PATH_PREFIXES)


def _apply_cors_headers(response: HttpResponse, origin: str) -> None:
    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Credentials"] = "true"
    response["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
    response["Access-Control-Allow-Headers"] = _ALLOWED_REQUEST_HEADERS
    response["Access-Control-Expose-Headers"] = _EXPOSED_RESPONSE_HEADERS
    # Reflect that the response varies by Origin so caches don't serve
    # the wrong CORS headers to a different origin.
    existing_vary = response.get("Vary", "")
    response["Vary"] = f"{existing_vary}, Origin" if existing_vary else "Origin"


class SBAdminMCPCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _path_is_mcp(request.path):
            return self.get_response(request)

        origin = request.META.get("HTTP_ORIGIN", "")
        allowed = bool(origin) and origin in _allowed_origins()

        is_preflight = (
            request.method == "OPTIONS"
            and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in request.META
        )
        if is_preflight:
            # Short-circuit preflight before the view runs — preflights
            # carry no auth, so letting them hit the OAuth-protected MCP
            # view would just turn into a 401 the browser can't read.
            response = HttpResponse(status=204)
            if allowed:
                _apply_cors_headers(response, origin)
            return response

        response = self.get_response(request)
        if allowed:
            _apply_cors_headers(response, origin)
        return response
