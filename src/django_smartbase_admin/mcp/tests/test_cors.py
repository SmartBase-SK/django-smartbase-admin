"""Cross-origin MCP / OAuth: preflight + actual request both return
the headers a browser-hosted MCP client needs."""

from __future__ import annotations

from django.test import TestCase


class _CorsBase(TestCase):
    ALLOWED_ORIGIN = "https://claude.ai"
    DENIED_ORIGIN = "https://evil.example.com"


class CorsPreflightTests(_CorsBase):
    def test_preflight_from_allowed_origin_returns_full_cors_headers(self):
        response = self.client.options(
            "/mcp/",
            HTTP_ORIGIN=self.ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="Authorization, Content-Type",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], self.ALLOWED_ORIGIN
        )
        # All three headers the OP flagged as missing must be present.
        self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])
        self.assertIn("OPTIONS", response.headers["Access-Control-Allow-Methods"])
        self.assertIn("Authorization", response.headers["Access-Control-Allow-Headers"])
        self.assertEqual(response.headers["Access-Control-Allow-Credentials"], "true")

    def test_preflight_from_disallowed_origin_omits_cors_headers(self):
        response = self.client.options(
            "/mcp/",
            HTTP_ORIGIN=self.DENIED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


class CorsActualRequestTests(_CorsBase):
    def test_unauth_post_from_allowed_origin_carries_cors_and_www_auth(self):
        """The 401 + WWW-Authenticate response must be readable cross-origin,
        otherwise the client can't extract ``resource_metadata`` to start
        OAuth — which is the exact failure mode the OP reported."""
        response = self.client.post(
            "/mcp/",
            data="{}",
            content_type="application/json",
            HTTP_ORIGIN=self.ALLOWED_ORIGIN,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], self.ALLOWED_ORIGIN
        )
        self.assertIn(
            "WWW-Authenticate",
            response.headers["Access-Control-Expose-Headers"],
        )


class CorsScopeTests(_CorsBase):
    def test_oauth_discovery_path_gets_cors_headers(self):
        response = self.client.get(
            "/.well-known/oauth-protected-resource",
            HTTP_ORIGIN=self.ALLOWED_ORIGIN,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], self.ALLOWED_ORIGIN
        )

    def test_non_mcp_path_is_untouched(self):
        """Unrelated views must not start emitting CORS — the middleware
        is path-scoped so it can't accidentally widen anyone's CORS posture.
        """
        # A path we know doesn't exist in the MCP urlconf — Django still
        # runs response middleware on the 404, so we can inspect headers.
        response = self.client.get(
            "/some/non-mcp/path", HTTP_ORIGIN=self.ALLOWED_ORIGIN
        )
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
