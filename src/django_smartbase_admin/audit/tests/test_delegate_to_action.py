"""Tests for delegate_to_action guard and permission checking."""

from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.test import RequestFactory, TestCase

from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.services.views import SBAdminViewService

PATCH_FROM_REQUEST = (
    "django_smartbase_admin.services.views"
    ".SBAdminViewRequestData.from_request_and_kwargs"
)


def _make_request_data(action_name, modifier="template"):
    rd = MagicMock()
    rd.action = action_name
    rd.modifier = modifier
    return rd


def _make_view(*, has_permission=True):
    view = MagicMock()

    @sbadmin_action
    def allowed_action(request, modifier):
        return HttpResponse("ok")

    def unmarked_method(request, modifier):
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

        mock_action = MagicMock()
        mock_action.target_view.as_view.return_value = (
            lambda request, **kwargs: HttpResponse("ok")
        )

        base_view = SBAdminBaseView.__new__(SBAdminBaseView)
        inner = base_view.delegate_to_action_view(mock_action)
        self.assertTrue(getattr(inner, "_is_sbadmin_action", False))


class TestSbadminActionDecorator(TestCase):
    def test_bare_decorator(self):
        @sbadmin_action
        def my_action(request, modifier):
            pass

        self.assertTrue(my_action._is_sbadmin_action)
        self.assertEqual(my_action._sbadmin_action_attrs, {})

    def test_decorator_with_kwargs(self):
        @sbadmin_action(permission="delete")
        def my_action(request, modifier):
            pass

        self.assertTrue(my_action._is_sbadmin_action)
        self.assertEqual(my_action._sbadmin_action_attrs["permission"], "delete")


class TestMenuActionAutoMarking(TestCase):
    def test_menu_action_method_is_auto_marked(self):
        class MyView(SBAdminView):
            menu_action = "landing"

            def landing(self, request, modifier):
                return HttpResponse("ok")

            def not_menu_action(self, request, modifier):
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
            def landing(self, request, modifier):
                return HttpResponse("ok")

        v = MyView()
        bound = v.landing
        fn = getattr(bound, "__func__", bound)
        self.assertTrue(getattr(fn, "_is_sbadmin_action", False))
        self.assertEqual(
            getattr(fn, "_sbadmin_action_attrs", {}).get("permission"), "delete"
        )
