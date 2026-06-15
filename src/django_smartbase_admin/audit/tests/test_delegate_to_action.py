"""Tests for delegate_to_action guard and permission checking."""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

from django_smartbase_admin.engine.actions import SBAdminCustomAction, sbadmin_action
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import Action
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.services.views import SBAdminViewService

PATCH_FROM_REQUEST = (
    "django_smartbase_admin.services.views"
    ".SBAdminViewRequestData.from_request_and_kwargs"
)


def _make_request_data(action_name, modifier="template"):
    rd = MagicMock()
    rd.action = action_name
    rd.modifier = modifier
    rd.object_id = None
    return rd


def _make_view(*, has_permission=True):
    view = MagicMock()

    @sbadmin_action
    def allowed_action(request, modifier, object_id):
        return HttpResponse("ok")

    def unmarked_method(request, modifier, object_id):
        return HttpResponse("should not reach")

    view.allowed_action = allowed_action
    view.unmarked_method = unmarked_method
    view.has_permission_for_action.return_value = has_permission
    view.init_view_dynamic = MagicMock()
    return view


class TestDelegateToAction(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch(PATCH_FROM_REQUEST)
    def test_marked_method_is_callable(self, mock_from_request):
        view = _make_view()
        rd = _make_request_data("allowed_action")
        rd.selected_view = view
        mock_from_request.return_value = rd

        request = self.factory.get("/")
        response = SBAdminViewService.delegate_to_action(
            request, view="v", action="allowed_action", modifier="template"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    @patch(PATCH_FROM_REQUEST)
    def test_unmarked_method_returns_404(self, mock_from_request):
        view = _make_view()
        rd = _make_request_data("unmarked_method")
        rd.selected_view = view
        mock_from_request.return_value = rd

        request = self.factory.get("/")
        with self.assertRaises(Http404):
            SBAdminViewService.delegate_to_action(
                request, view="v", action="unmarked_method", modifier="template"
            )

    @patch(PATCH_FROM_REQUEST)
    def test_permission_denied(self, mock_from_request):
        view = _make_view(has_permission=False)
        rd = _make_request_data("allowed_action")
        rd.selected_view = view
        mock_from_request.return_value = rd

        request = self.factory.get("/")
        with self.assertRaises(PermissionDenied):
            SBAdminViewService.delegate_to_action(
                request, view="v", action="allowed_action", modifier="template"
            )

    def test_dynamic_inner_view_is_marked(self):
        from django_smartbase_admin.engine.admin_base_view import SBAdminBaseView

        seen_kwargs = {}
        mock_action = MagicMock()

        def target_callable(request, **kwargs):
            seen_kwargs.update(kwargs)
            return HttpResponse("ok")

        mock_action.target_view.as_view.return_value = target_callable

        base_view = SBAdminBaseView.__new__(SBAdminBaseView)
        inner = base_view.delegate_to_target_view(mock_action.target_view)
        response = inner(self.factory.get("/"), "template", "123")

        self.assertTrue(getattr(inner, "_is_sbadmin_action", False))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen_kwargs, {"modifier": "template", "object_id": "123"})

    @patch(PATCH_FROM_REQUEST)
    def test_decorator_permission_propagated_to_action(self, mock_from_request):
        @sbadmin_action(permission="delete")
        def restricted_action(request, modifier, object_id):
            return HttpResponse("ok")

        view = MagicMock()
        view.restricted_action = restricted_action
        view.has_permission_for_action.return_value = True
        view.init_view_dynamic = MagicMock()

        rd = _make_request_data("restricted_action")
        rd.selected_view = view
        mock_from_request.return_value = rd

        SBAdminViewService.delegate_to_action(
            self.factory.get("/"),
            view="v",
            action="restricted_action",
            modifier="template",
        )

        action_arg = view.has_permission_for_action.call_args.args[1]
        self.assertEqual(action_arg.permission, "delete")

    @patch(PATCH_FROM_REQUEST)
    def test_object_id_is_passed_to_method_action_for_template_modifier(
        self, mock_from_request
    ):
        seen = {}

        @sbadmin_action
        def row_action(request, modifier, object_id):
            seen["modifier"] = modifier
            seen["object_id"] = object_id
            return HttpResponse("ok")

        view = MagicMock()
        view.row_action = row_action
        view.has_permission_for_action.return_value = True
        view.init_view_dynamic = MagicMock()

        rd = _make_request_data("row_action", modifier="template")
        rd.object_id = "123"
        rd.selected_view = view
        mock_from_request.return_value = rd

        response = SBAdminViewService.delegate_to_action(
            self.factory.get("/"),
            view="v",
            action="row_action",
            modifier="template",
            object_id="123",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["modifier"], "template")
        self.assertEqual(seen["object_id"], "123")


class TestDefaultActionPermission(TestCase):
    """Custom actions with no explicit ``permission`` must default to
    requiring ``change`` — read-only endpoints opt out via
    ``@sbadmin_action(permission="view")``."""

    def test_default_requires_change(self):
        config = SBAdminRoleConfiguration()
        action = SBAdminCustomAction.__new__(SBAdminCustomAction)
        action.action_id = "some_action"
        action.permission = None

        with patch.object(config, "has_permission") as has_perm:
            config.has_action_permission(
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
                None,
                action,
            )

        self.assertEqual(has_perm.call_args.args[-1], "change")


class MCPReadonlyRoleConfiguration(SBAdminRoleConfiguration):
    mcp_readonly = True


class MCPReadonlyOverrideRoleConfiguration(MCPReadonlyRoleConfiguration):
    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        return True


class LegacyRoleConfiguration:
    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        return True


class TestMCPReadonlyPermissions(TestCase):
    def _request(self, *, is_mcp=True, is_superuser=False, has_perm=True):
        request = RequestFactory().get("/")
        request.is_mcp = is_mcp
        request.user = MagicMock(is_superuser=is_superuser, is_staff=True)
        request.user.has_perm.return_value = has_perm
        return request

    def test_mcp_readonly_blocks_model_writes_only_for_mcp_requests(self):
        config = MCPReadonlyRoleConfiguration()
        view = MagicMock()

        mcp_request = self._request(is_mcp=True)
        self.assertTrue(
            config.has_permission(mcp_request, MagicMock(), view, Group, None, "view")
        )
        self.assertFalse(
            config.has_permission(mcp_request, MagicMock(), view, Group, None, "add")
        )
        self.assertFalse(
            config.has_permission(mcp_request, MagicMock(), view, Group, None, "change")
        )
        self.assertFalse(
            config.has_permission(mcp_request, MagicMock(), view, Group, None, "delete")
        )

        browser_request = self._request(is_mcp=False)
        self.assertTrue(
            config.has_permission(
                browser_request, MagicMock(), view, Group, None, "change"
            )
        )

    def test_mcp_readonly_blocks_mutating_actions_but_allows_view_actions(self):
        config = MCPReadonlyRoleConfiguration()
        request = self._request()
        view = MagicMock()

        mutate_action = SBAdminCustomAction.__new__(SBAdminCustomAction)
        mutate_action.action_id = "mutate"
        mutate_action.permission = None

        view_action = SBAdminCustomAction.__new__(SBAdminCustomAction)
        view_action.action_id = "inspect"
        view_action.permission = "view"

        delete_action = SBAdminCustomAction.__new__(SBAdminCustomAction)
        delete_action.action_id = Action.BULK_DELETE.value
        delete_action.permission = "delete"

        self.assertFalse(
            config.has_action_permission(
                request, MagicMock(), view, Group, None, mutate_action
            )
        )
        self.assertFalse(
            config.has_action_permission(
                request, MagicMock(), view, Group, None, delete_action
            )
        )
        self.assertTrue(
            config.has_action_permission(
                request, MagicMock(), view, Group, None, view_action
            )
        )
        view.has_delete_permission.assert_not_called()

    def test_mcp_readonly_does_not_block_superusers(self):
        config = MCPReadonlyRoleConfiguration()
        request = self._request(is_superuser=True)

        self.assertTrue(
            config.has_permission(
                request, MagicMock(), MagicMock(), Group, None, "change"
            )
        )

    def test_service_gate_applies_before_custom_has_permission_override(self):
        request = self._request()
        request.request_data = MagicMock()
        request.request_data.configuration = MCPReadonlyOverrideRoleConfiguration()

        self.assertFalse(
            SBAdminViewService.has_permission(
                request, view=MagicMock(), model=Group, permission="change"
            )
        )
        self.assertTrue(
            SBAdminViewService.has_permission(
                request, view=MagicMock(), model=Group, permission="view"
            )
        )

    def test_service_gate_allows_legacy_configuration_without_mcp_helper(self):
        request = self._request()
        request.request_data = MagicMock()
        request.request_data.configuration = LegacyRoleConfiguration()

        self.assertTrue(
            SBAdminViewService.has_permission(
                request, view=MagicMock(), model=Group, permission="change"
            )
        )

    def test_default_bulk_delete_action_declares_delete_permission(self):
        view = SBAdminBaseListView.__new__(SBAdminBaseListView)
        view.model = Group
        view.sbadmin_list_selection_actions = None

        action = next(
            action
            for action in view.get_sbadmin_list_selection_actions(MagicMock())
            if action.action_id == Action.BULK_DELETE.value
        )

        self.assertEqual(action.permission, "delete")


class TestSbadminActionDecorator(TestCase):
    def test_bare_decorator(self):
        @sbadmin_action
        def my_action(request, modifier, object_id):
            pass

        self.assertTrue(my_action._is_sbadmin_action)
        self.assertEqual(my_action._sbadmin_action_attrs, {})

    def test_decorator_with_kwargs(self):
        @sbadmin_action(permission="delete")
        def my_action(request, modifier, object_id):
            pass

        self.assertTrue(my_action._is_sbadmin_action)
        self.assertEqual(my_action._sbadmin_action_attrs["permission"], "delete")


class TestMenuActionAutoMarking(TestCase):
    def test_menu_action_method_is_auto_marked(self):
        class MyView(SBAdminView):
            menu_action = "landing"

            def landing(self, request, modifier, object_id):
                return HttpResponse("ok")

            def not_menu_action(self, request, modifier, object_id):
                return HttpResponse("nope")

        v = MyView()
        bound = v.landing
        fn = getattr(bound, "__func__", bound)
        self.assertTrue(getattr(fn, "_is_sbadmin_action", False))
        bound = v.not_menu_action
        fn = getattr(bound, "__func__", bound)
        self.assertFalse(getattr(fn, "_is_sbadmin_action", False))

    def test_menu_action_decorator_kwargs_are_preserved(self):
        class MyView(SBAdminView):
            menu_action = "landing"

            @sbadmin_action(permission="delete")
            def landing(self, request, modifier, object_id):
                return HttpResponse("ok")

        v = MyView()
        bound = v.landing
        fn = getattr(bound, "__func__", bound)
        self.assertTrue(getattr(fn, "_is_sbadmin_action", False))
        self.assertEqual(
            getattr(fn, "_sbadmin_action_attrs", {}).get("permission"), "delete"
        )
