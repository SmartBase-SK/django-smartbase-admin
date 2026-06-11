"""Minimal DOT validator for the SBAdmin MCP OAuth server.

``OAUTH2_PROVIDER["ALLOWED_REDIRECT_URI_SCHEMES"]`` is a global, host-blind
scheme list. Allowing ``"http"`` so a local (``http://localhost``) dashboard
can register a redirect URI would otherwise permit an http redirect to *any*
host. This validator narrows http to loopback hosts (RFC 8252 §7.3); https and
native custom schemes (``cursor://``, ``claude://``) are unaffected.

It also relaxes DOT's exact-match for loopback redirects: native MCP clients
(Claude Code, Cursor) bind an ephemeral localhost port per auth run, so the
port registered at DCR time never matches later runs. RFC 8252 §7.3 requires
the AS to allow any port for loopback redirect URIs.

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


def loopback_redirect_allowed(redirect_uri: str, allowed_uris) -> bool:
    """RFC 8252 §7.3 — match a loopback redirect URI ignoring its port.

    Loopback hosts are treated as interchangeable (a client registered with
    ``127.0.0.1`` may come back as ``localhost``); scheme, path and query must
    still match a registered loopback URI exactly.
    """
    requested = urlsplit(redirect_uri)
    if requested.hostname not in LOOPBACK_HOSTS:
        return False
    for allowed in allowed_uris:
        candidate = urlsplit(allowed)
        if (
            candidate.hostname in LOOPBACK_HOSTS
            and candidate.scheme == requested.scheme
            and candidate.path == requested.path
            and candidate.query == requested.query
        ):
            return True
    return False


class SBAdminMCPOAuth2Validator(OAuth2Validator):
    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        if is_non_loopback_http(redirect_uri):
            return False
        if super().validate_redirect_uri(
            client_id, redirect_uri, request, *args, **kwargs
        ):
            return True
        client = getattr(request, "client", None)
        if client is None:
            return False
        return loopback_redirect_allowed(redirect_uri, client.redirect_uris.split())
