"""End-to-end smoke test for the MCP transport + bundled OAuth 2.1 AS.

Covers the full happy path a real MCP client (Cursor, Claude Code) walks
through on first connect:

* RFC 8414 / 9728 discovery
* RFC 7591 dynamic client registration
* PKCE authorize -> code -> token (DOT-backed)
* MCP ``initialize`` + ``tools/list`` + ``tools/call list_admins`` over
  plain Django POST (no SSE session reuse — ``stateless=True`` mode)
* Unauthenticated MCP call -> 401 with ``WWW-Authenticate``

The tests run against ``tests.mcp_urls``, the same combined URLconf a
project would wire when opting into ``django_smartbase_admin.mcp.oauth``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@override_settings(ROOT_URLCONF="tests.mcp_urls")
class MCPOAuthSmokeTests(TestCase):
    """End-to-end OAuth 2.1 + MCP transport smoke."""

    REDIRECT_URI = "http://127.0.0.1:5555/cb"
    SCOPE = "sbadmin:read"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # DOT refuses non-HTTPS authorize/token by default; this matches
        # what every dev/test setup does.
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create(username="alice", is_active=True)
        self.user.set_password("pw")
        self.user.save()
        self.client = Client()
        self.assertTrue(
            self.client.login(username="alice", password="pw"),
            "test user failed to log in",
        )

    # --- discovery + DCR -------------------------------------------------

    def test_authorization_server_metadata(self):
        r = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertTrue(
            data["registration_endpoint"].endswith("/oauth/register"),
            data,
        )
        self.assertIn("S256", data["code_challenge_methods_supported"])
        self.assertIn(self.SCOPE, data["scopes_supported"])

    def test_protected_resource_metadata(self):
        r = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertTrue(data["resource"].endswith("/mcp/"), data)
        self.assertEqual(data["bearer_methods_supported"], ["header"])

    def test_dynamic_client_registration_minimal(self):
        client_data = self._register_client()
        self.assertTrue(client_data["client_id"])
        self.assertEqual(client_data["token_endpoint_auth_method"], "none")
        self.assertEqual(client_data["redirect_uris"], [self.REDIRECT_URI])

    def test_dcr_rejects_missing_redirect_uris(self):
        r = self.client.post(
            "/oauth/register",
            data=json.dumps({"client_name": "smoke"}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()["error"], "invalid_redirect_uri")

    # --- end-to-end OAuth + MCP flow ------------------------------------

    def test_full_oauth_then_mcp_flow(self):
        token = self._issue_access_token()

        # Unauthenticated MCP call -> 401.
        r = self._mcp_call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            token=None,
        )
        self.assertIn(r.status_code, (401, 403), (r.status_code, r.content[:200]))

        # initialize.
        r = self._mcp_call(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            },
            token=token,
        )
        self.assertEqual(r.status_code, 200, (r.status_code, r.content[:500]))
        init = self._parse_mcp_response(r)["result"]
        self.assertEqual(init["serverInfo"]["name"], "sbadmin")
        self.assertTrue(init["protocolVersion"])

        # initialized notification (no id, server returns 202).
        r = self._mcp_call(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            token=token,
        )
        self.assertIn(r.status_code, (200, 202), (r.status_code, r.content[:200]))

        # tools/list -> list_admins must be present.
        r = self._mcp_call(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            token=token,
        )
        self.assertEqual(r.status_code, 200, (r.status_code, r.content[:500]))
        tools = [t["name"] for t in self._parse_mcp_response(r)["result"]["tools"]]
        self.assertIn("list_admins", tools, tools)

        # tools/call list_admins. No SBAdmin admins are registered in
        # this test setup, so we just assert the call succeeds and
        # returns a list — this proves the toolset class is wired and
        # ``self.request.user`` reaches the SBAdmin pipeline.
        r = self._mcp_call(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_admins", "arguments": {}},
            },
            token=token,
        )
        self.assertEqual(r.status_code, 200, (r.status_code, r.content[:500]))
        payload = self._parse_mcp_response(r)
        self.assertNotIn("error", payload, payload)
        self.assertIn("result", payload, payload)
        result = payload["result"]
        self.assertFalse(result.get("isError"), payload)
        # No SBAdmin admins are registered for tests, so the structured
        # tool result is an empty list.
        self.assertEqual(result["structuredContent"]["result"], [])

    # --- helpers ---------------------------------------------------------

    def _register_client(self) -> dict:
        r = self.client.post(
            "/oauth/register",
            data=json.dumps(
                {
                    "client_name": "smoke",
                    "redirect_uris": [self.REDIRECT_URI],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _issue_access_token(self) -> str:
        client_data = self._register_client()
        client_id = client_data["client_id"]

        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

        # GET authorize: confirms the page renders for the logged-in user.
        auth_url = (
            "/o/authorize/"
            "?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={self.REDIRECT_URI}"
            f"&scope={self.SCOPE}"
            f"&code_challenge={challenge}"
            "&code_challenge_method=S256"
            "&state=xyz"
        )
        r = self.client.get(auth_url)
        self.assertEqual(r.status_code, 200, (r.status_code, r.content[:300]))

        # POST consent -> redirect with ?code=...
        r = self.client.post(
            "/o/authorize/",
            data={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": self.REDIRECT_URI,
                "scope": self.SCOPE,
                "state": "xyz",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "allow": "Authorize",
            },
        )
        self.assertEqual(r.status_code, 302, (r.status_code, r.content[:300]))
        code = parse_qs(urlparse(r["Location"]).query)["code"][0]

        # Exchange code for token.
        r = self.client.post(
            "/o/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        self.assertEqual(r.status_code, 200, (r.status_code, r.content[:300]))
        tok = r.json()
        self.assertEqual(tok["scope"], self.SCOPE)
        return tok["access_token"]

    def _mcp_call(self, body, *, token: str | None):
        headers = {"HTTP_ACCEPT": "application/json, text/event-stream"}
        if token:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.post(
            "/mcp/",
            data=json.dumps(body),
            content_type="application/json",
            **headers,
        )

    @staticmethod
    def _parse_mcp_response(resp):
        """``django-mcp-server`` SSE-frames JSON-RPC bodies on tools/* calls."""
        body = resp.content.decode()
        ct = resp["Content-Type"].split(";")[0].strip()
        if ct == "application/json":
            return json.loads(body)
        if ct == "text/event-stream":
            for line in body.splitlines():
                if line.startswith("data:"):
                    return json.loads(line.removeprefix("data:").strip())
        raise AssertionError(f"unexpected content-type: {ct}\nbody: {body[:300]}")
