"""CORS middleware: which origins/paths get headers, and the no-credentials default.

The dashboard + browser MCP clients authenticate with a Bearer token and a
public-client PKCE OAuth flow, so no cross-origin request needs cookies. The
middleware must therefore not advertise credentials by default, and must keep
the cookie-authed (navigation-only) authorize endpoint off the CORS surface.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from django_smartbase_admin.mcp.middleware import SBAdminMCPCorsMiddleware

ORIGIN = "http://localhost:8010"


@override_settings(SBADMIN_MCP_ALLOWED_ORIGINS=[ORIGIN])
class CorsMiddlewareTests(SimpleTestCase):
    def _send(self, path, *, origin=ORIGIN, method="post", preflight=False):
        rf = RequestFactory()
        extra = {"HTTP_ORIGIN": origin} if origin else {}
        if preflight:
            extra["HTTP_ACCESS_CONTROL_REQUEST_METHOD"] = "POST"
            request = rf.options(path, **extra)
        else:
            request = getattr(rf, method)(path, **extra)
        middleware = SBAdminMCPCorsMiddleware(lambda r: HttpResponse("ok"))
        return middleware(request)

    def test_allowed_origin_gets_cors_without_credentials_by_default(self):
        resp = self._send("/mcp/")
        self.assertEqual(resp["Access-Control-Allow-Origin"], ORIGIN)
        self.assertNotIn("Access-Control-Allow-Credentials", resp)
        self.assertIn("Origin", resp["Vary"])

        pre = self._send("/mcp/", preflight=True)
        self.assertEqual(pre.status_code, 204)
        self.assertEqual(pre["Access-Control-Allow-Origin"], ORIGIN)
        self.assertNotIn("Access-Control-Allow-Credentials", pre)

    def test_mcp_rest_and_oauth_paths_are_decorated(self):
        for path in (
            "/mcp/",
            "/mcp/rest/tools/list_rows/",
            "/o/token/",
            "/.well-known/oauth-authorization-server",
        ):
            self.assertEqual(
                self._send(path, method="get")["Access-Control-Allow-Origin"], ORIGIN
            )

    def test_preflight_uses_default_allowed_headers(self):
        resp = self._send("/mcp/rest/tools/list_rows/", preflight=True)

        allowed_headers = resp["Access-Control-Allow-Headers"]
        self.assertIn("Authorization", allowed_headers)
        self.assertIn("Content-Type", allowed_headers)
        self.assertNotIn("X-App-Secret", allowed_headers)
        self.assertNotIn("X-Shop-Id", allowed_headers)

    @override_settings(
        SBADMIN_MCP_ALLOWED_HEADERS=[
            "Authorization",
            "Content-Type",
            "MCP-Protocol-Version",
            "MCP-Session-Id",
            "X-App-Secret",
            "X-Shop-Id",
        ]
    )
    def test_preflight_allows_project_configured_headers(self):
        resp = self._send("/mcp/rest/tools/list_rows/", preflight=True)

        allowed_headers = resp["Access-Control-Allow-Headers"]
        self.assertIn("X-App-Secret", allowed_headers)
        self.assertIn("X-Shop-Id", allowed_headers)

    def test_disallowed_origin_and_unrelated_paths_get_no_cors(self):
        self.assertNotIn(
            "Access-Control-Allow-Origin",
            self._send("/mcp/", origin="http://evil.example"),
        )
        self.assertNotIn(
            "Access-Control-Allow-Origin", self._send("/admin/", method="get")
        )
