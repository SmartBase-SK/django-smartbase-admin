"""Shared fixtures for MCP tool tests.

Keeps the per-test admin swap pattern and the real ``SBAdminRoleConfiguration``
subclass (rather than a ``MagicMock``) in one place. ``MagicMock`` would
silently break configuration contracts that only manifest when the actual
list/autocomplete pipelines run — e.g. ``get_filter_widget``'s pass-through
default would be replaced by a fresh mock from every call.
"""

from __future__ import annotations

from django.test import RequestFactory
from rest_framework.request import Request

from django_smartbase_admin.engine.request import SBAdminViewRequestData

from tests.sbadmin_config import MCPToolTestConfig

__all__ = ["MCPToolTestConfig", "build_mcp_request"]


def build_mcp_request(user, *, path: str = "/mcp/"):
    """DRF-wrapped request pre-bridged into the SBAdmin pipeline.

    Wraps a ``RequestFactory`` ``WSGIRequest`` in a DRF ``Request`` so
    tests exercise the same request shape ``django-mcp-server`` hands
    to ``SBAdminTools`` in production — ``request.POST`` / ``GET`` /
    ``method`` go through DRF's read-only properties, ``request.user``
    / ``request.session`` are attached directly on the wrapper.

    Tests can still mutate ``request.request_data.request_get`` /
    ``request_post`` directly to drive each tool.
    """
    wsgi = RequestFactory().get(path)
    request = Request(wsgi)
    request.user = user
    request.session = {}

    request_data = SBAdminViewRequestData(
        view=None,
        action=None,
        modifier=None,
        user=user,
        request_get=request.GET,
        request_method="GET",
    )
    request_data.additional_data = {}
    request_data.configuration = MCPToolTestConfig()
    request.request_data = request_data
    request.LANGUAGE_CODE = "en"
    return request
