"""Shared fixtures for MCP tool tests.

Keeps the per-test admin swap pattern and the real ``SBAdminRoleConfiguration``
subclass (rather than a ``MagicMock``) in one place. ``MagicMock`` would
silently break configuration contracts that only manifest when the actual
list/autocomplete pipelines run — e.g. ``get_filter_widget``'s pass-through
default would be replaced by a fresh mock from every call.
"""

from __future__ import annotations

from django.test import RequestFactory

from django_smartbase_admin.engine.request import SBAdminViewRequestData

from tests.sbadmin_config import MCPToolTestConfig


__all__ = ["MCPToolTestConfig", "build_mcp_request"]


def build_mcp_request(user, *, path: str = "/mcp/"):
    """``RequestFactory`` request pre-bridged into the SBAdmin pipeline.

    Mirrors what ``ensure_sbadmin_request_data`` would set up on a real
    incoming MCP/DRF request, but uses the real ``MCPToolTestConfig`` so
    ``get_filter_widget`` / ``restrict_queryset`` / ``has_permission``
    follow their documented contracts. Tests can mutate
    ``request.request_data.request_get`` / ``request_post`` directly to
    drive each tool. We also stub ``request.session`` because
    ``SBAdminViewRequestData.from_request_and_kwargs`` (reached via
    ``delegate_to_action``) reads ``request.session.get(...)`` directly;
    ``RequestFactory`` does not attach a session.
    """
    request = RequestFactory().get(path)
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
