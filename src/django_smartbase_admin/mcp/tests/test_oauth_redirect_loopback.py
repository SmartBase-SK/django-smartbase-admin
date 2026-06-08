"""Loopback-only http redirect URIs — the validator gate and the DCR endpoint.

``ALLOWED_REDIRECT_URI_SCHEMES`` must keep "http" so a local dashboard can
register a loopback redirect, but http to any other host must be refused. Both
the authorize-time validator and the registration endpoint enforce that.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from oauth2_provider.oauth2_validators import OAuth2Validator

from django_smartbase_admin.mcp.oauth.validators import (
    SBAdminMCPOAuth2Validator,
    is_non_loopback_http,
)
from django_smartbase_admin.mcp.oauth.views import register


class LoopbackRedirectTests(TestCase):
    def test_is_non_loopback_http_truth_table(self):
        for uri in (
            "http://evil.example/cb",
            "http://192.168.0.5:8010/",
            "http://example.com/",
        ):
            self.assertTrue(is_non_loopback_http(uri), uri)
        for uri in (
            "http://localhost:8010/",
            "http://127.0.0.1/cb",
            "http://[::1]:8010/",
            "https://anything.example/cb",
            "cursor://callback",
        ):
            self.assertFalse(is_non_loopback_http(uri), uri)

    def test_validator_rejects_non_loopback_http_only(self):
        validator = SBAdminMCPOAuth2Validator()
        with patch.object(OAuth2Validator, "validate_redirect_uri", return_value=True) as parent:
            self.assertFalse(
                validator.validate_redirect_uri("c", "http://evil.example/cb", SimpleNamespace())
            )
            parent.assert_not_called()
        with patch.object(OAuth2Validator, "validate_redirect_uri", return_value=True) as parent:
            self.assertTrue(
                validator.validate_redirect_uri("c", "http://localhost:8010/", SimpleNamespace())
            )
            parent.assert_called_once()

    def test_dcr_register_enforces_loopback_for_http(self):
        rf = RequestFactory()

        def _register(uris):
            request = rf.post(
                "/oauth/register",
                data=json.dumps({"redirect_uris": uris}),
                content_type="application/json",
            )
            return register(request)

        bad = _register(["http://evil.example/cb"])
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(json.loads(bad.content)["error"], "invalid_redirect_uri")

        ok = _register(["http://localhost:8010/"])
        self.assertEqual(ok.status_code, 201)
        self.assertIn("client_id", json.loads(ok.content))
