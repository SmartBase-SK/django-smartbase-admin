from __future__ import annotations

from unittest.mock import MagicMock

from django.http import Http404
from django.test import SimpleTestCase
from django_smartbase_admin.mcp.mcp import SBAdminTools, _guarded_tool_call
from django_smartbase_admin.mcp.rest import (
    SBAdminMCPRestAuthenticator,
    SBAdminMCPRestCapabilitiesAPIView,
    SBAdminMCPToolAPIView,
    SBAdminMCPToolsManifestAPIView,
    call_sbadmin_mcp_tool,
    get_sbadmin_mcp_rest_capabilities,
    list_sbadmin_mcp_tools,
    resolve_guarded_mcp_tool,
)
from django_smartbase_admin.mcp.tests._common import build_mcp_request
from rest_framework.test import APIRequestFactory


def _staff_user():
    return MagicMock(is_active=True, is_staff=True, is_authenticated=True)


class RestDispatchTools(SBAdminTools):
    @_guarded_tool_call
    def ping(self, value: str) -> dict:
        return {"value": value}

    def accidental_public_helper(self) -> dict:
        return {"unsafe": True}


class RestDispatchTests(SimpleTestCase):
    def test_dispatch_calls_guarded_tool(self):
        request = build_mcp_request(_staff_user())

        result = call_sbadmin_mcp_tool(
            request=request,
            tool_name="ping",
            arguments={"value": "ok"},
            toolset_cls=RestDispatchTools,
        )

        self.assertEqual(result, {"value": "ok"})

    def test_dispatch_rejects_undecorated_public_method(self):
        toolset = RestDispatchTools(request=build_mcp_request(_staff_user()))

        with self.assertRaises(Http404):
            resolve_guarded_mcp_tool(toolset, "accidental_public_helper")

    def test_dispatch_rejects_unknown_tool(self):
        request = build_mcp_request(_staff_user())

        with self.assertRaises(Http404):
            call_sbadmin_mcp_tool(
                request=request,
                tool_name="missing",
                arguments={},
                toolset_cls=RestDispatchTools,
            )

    def test_list_tools_describes_guarded_tools_only(self):
        request = build_mcp_request(_staff_user())

        result = list_sbadmin_mcp_tools(request=request, toolset_cls=RestDispatchTools)

        tool_names = [tool["name"] for tool in result["tools"]]
        self.assertIn("ping", tool_names)
        self.assertNotIn("accidental_public_helper", tool_names)
        ping = next(tool for tool in result["tools"] if tool["name"] == "ping")
        self.assertEqual(ping["input_schema"]["required"], ["value"])
        self.assertEqual(ping["input_schema"]["properties"]["value"]["type"], "string")

    def test_capabilities_advertise_rest_tool_support(self):
        result = get_sbadmin_mcp_rest_capabilities(toolset_cls=RestDispatchTools)

        self.assertEqual(result["protocol"], "sbadmin-mcp-rest")
        self.assertTrue(result["capabilities"]["tools"]["list"])
        self.assertTrue(result["capabilities"]["tools"]["call"])


class StaticAuthenticator(SBAdminMCPRestAuthenticator):
    def __init__(self, user):
        self.user = user

    def authenticate(self, request, **kwargs):
        return self.user


class RestViewTests(SimpleTestCase):
    def test_view_uses_authenticator_user_and_dispatches_tool(self):
        user = _staff_user()
        view = SBAdminMCPToolAPIView.as_view(
            authenticator=StaticAuthenticator(user),
            toolset_cls=RestDispatchTools,
        )
        request = APIRequestFactory().post(
            "/mcp-rest/tools/ping/",
            {"value": "ok"},
            format="json",
        )

        response = view(request, tool_name="ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"value": "ok"})

    def test_view_rejects_undecorated_public_method(self):
        user = _staff_user()
        view = SBAdminMCPToolAPIView.as_view(
            authenticator=StaticAuthenticator(user),
            toolset_cls=RestDispatchTools,
        )
        request = APIRequestFactory().post(
            "/mcp-rest/tools/accidental_public_helper/",
            {},
            format="json",
        )

        response = view(request, tool_name="accidental_public_helper")

        self.assertEqual(response.status_code, 404)

    def test_manifest_view_uses_authenticator_and_lists_tools(self):
        user = _staff_user()
        view = SBAdminMCPToolsManifestAPIView.as_view(
            authenticator=StaticAuthenticator(user),
            toolset_cls=RestDispatchTools,
        )
        request = APIRequestFactory().get("/mcp-rest/tools/")

        response = view(request)

        self.assertEqual(response.status_code, 200)
        tool_names = [tool["name"] for tool in response.data["tools"]]
        self.assertIn("ping", tool_names)
        self.assertNotIn("accidental_public_helper", tool_names)

    def test_capabilities_view_uses_authenticator(self):
        user = _staff_user()
        view = SBAdminMCPRestCapabilitiesAPIView.as_view(
            authenticator=StaticAuthenticator(user),
            toolset_cls=RestDispatchTools,
        )
        request = APIRequestFactory().get("/mcp-rest/")

        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["protocol"], "sbadmin-mcp-rest")
