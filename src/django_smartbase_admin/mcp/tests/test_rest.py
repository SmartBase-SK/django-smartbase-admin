from __future__ import annotations

from unittest.mock import MagicMock

from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django_smartbase_admin.mcp.mcp import SBAdminTools, _guarded_tool_call
from django_smartbase_admin.mcp.rest import (
    SBAdminMCPRestAuthenticator,
    SBAdminMCPToolAPIView,
    call_sbadmin_mcp_tool,
    resolve_guarded_mcp_tool,
    resolve_sbadmin_mcp_rest_authenticator,
)
from django_smartbase_admin.mcp.tests._common import build_mcp_request
from rest_framework.authentication import BaseAuthentication
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


class StaticAuthenticator(SBAdminMCPRestAuthenticator):
    def __init__(self, user):
        self.user = user

    def authenticate(self, request, **kwargs):
        return self.user


class TupleAuthenticator(SBAdminMCPRestAuthenticator):
    def __init__(self, user):
        self.user = user

    def authenticate(self, request, **kwargs):
        return self.user, None


class SettingsAuthenticator(SBAdminMCPRestAuthenticator):
    def authenticate(self, request, **kwargs):
        return _staff_user()


class RestViewTests(SimpleTestCase):
    def test_rest_authenticator_extends_drf_base_authentication(self):
        self.assertTrue(issubclass(SBAdminMCPRestAuthenticator, BaseAuthentication))

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

    def test_view_accepts_drf_authenticate_tuple(self):
        user = _staff_user()
        view = SBAdminMCPToolAPIView.as_view(
            authenticator=TupleAuthenticator(user),
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

    @override_settings(
        SBADMIN_MCP_REST_AUTHENTICATOR=(
            "django_smartbase_admin.mcp.tests.test_rest.SettingsAuthenticator"
        )
    )
    def test_view_uses_settings_authenticator(self):
        view = SBAdminMCPToolAPIView.as_view(toolset_cls=RestDispatchTools)
        request = APIRequestFactory().post(
            "/mcp-rest/tools/ping/",
            {"value": "ok"},
            format="json",
        )

        response = view(request, tool_name="ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"value": "ok"})

    @override_settings(SBADMIN_MCP_REST_AUTHENTICATOR=None)
    def test_missing_settings_authenticator_is_configuration_error(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_sbadmin_mcp_rest_authenticator()


@override_settings(ROOT_URLCONF="django_smartbase_admin.mcp.urls")
class RestURLTests(SimpleTestCase):
    def test_main_urls_include_fixed_list_rows_rest_route(self):
        self.assertEqual(
            reverse("sbadmin_mcp_rest_tool"),
            "/rest/tools/list_rows/",
        )
