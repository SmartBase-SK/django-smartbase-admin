"""Minimal DOT validator for the SBAdmin MCP OAuth server.

``OAUTH2_PROVIDER["ALLOWED_REDIRECT_URI_SCHEMES"]`` is a global, host-blind
scheme list. Allowing ``"http"`` so a local (``http://localhost``) dashboard
can register a redirect URI would otherwise permit an http redirect to *any*
host. This validator narrows http to loopback hosts (RFC 8252 §7.3); https and
native custom schemes (``cursor://``, ``claude://``) are unaffected.

Wire it in as ``OAUTH2_PROVIDER["OAUTH2_VALIDATOR_CLASS"]``, or subclass it if
the deployment needs further customization.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from oauth2_provider.oauth2_validators import OAuth2Validator

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_non_loopback_http(redirect_uri: str) -> bool:
    """True for an ``http://`` URI whose host is not a loopback literal."""
    parts = urlsplit(redirect_uri)
    return parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS


class SBAdminMCPOAuth2Validator(OAuth2Validator):
    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        if is_non_loopback_http(redirect_uri):
            return False
        return super().validate_redirect_uri(
            client_id, redirect_uri, request, *args, **kwargs
        )
