"""``SBAdminMCPOAuth2Authentication`` end-to-end:

an unauthenticated request to ``/mcp/`` returns ``401`` with a
``WWW-Authenticate: Bearer ... resource_metadata="..."`` header.
Without that header MCP clients (Cursor, Claude, Cowork) can't discover
the authorization server and refuse to install the integration.
"""

from __future__ import annotations

from django.test import TestCase


class MCPUnauthenticatedResponseTests(TestCase):
    def test_unauth_request_returns_401_with_resource_metadata_header(self):
        response = self.client.post("/mcp/", data="{}", content_type="application/json")

        self.assertEqual(response.status_code, 401)
        www_auth = response.headers.get("WWW-Authenticate", "")
        self.assertTrue(
            www_auth.startswith("Bearer "),
            f"expected Bearer challenge, got: {www_auth!r}",
        )
        self.assertIn("resource_metadata=", www_auth)
        # Must point at the protected-resource metadata endpoint.
        self.assertIn("/.well-known/oauth-protected-resource", www_auth)
