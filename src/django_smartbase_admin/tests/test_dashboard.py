from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth.models import User
from django.db.models import F
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import render_to_string
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.engine.const import Action
from django_smartbase_admin.engine.dashboard import (
    SBAdminDashboardListWidget,
    render_registered_standalone_widget,
)
from django_smartbase_admin.engine.field import SBAdminField


class _DashboardWidget(SBAdminDashboardListWidget):
    model = User
    sbadmin_list_display = (SBAdminField(name="display_name", annotate=F("username")),)

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def init_actions(self, request):
        pass

    @admin.display(description="Display name")
    def display_name(self, object_id, value, **kwargs):
        return value


class _StandaloneDashboardWidget(SBAdminDashboardListWidget):
    widget_id = "embedded_dashboard_widget"
    model = User
    sbadmin_list_display = (SBAdminField(name="display_name", annotate=F("username")),)

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def init_actions(self, request):
        pass

    def get_detail_url(self):
        return ""

    def get_action_url(self, action, modifier="template", object_id=None):
        url = f"/{self.get_id()}/{action}/{modifier}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

    @admin.display(description="Display name")
    def display_name(self, object_id, value, **kwargs):
        return value


class _StandaloneNoHeaderDashboardWidget(_StandaloneDashboardWidget):
    widget_id = "embedded_no_header_dashboard_widget"
    search_fields = ("display_name",)
    sbadmin_show_tabulator_header_controls = False
    sbadmin_filters_open_by_default = True


class _RenderedRegisteredWidget:
    def init_view_dynamic(self, request, request_data=None, **kwargs):
        self.initialized_request = request
        self.initialized_request_data = request_data

    def render(self, request):
        self.render_request = request
        return "<div>Rendered widget</div>"


class TestSBAdminDashboardListWidget(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_init_view_dynamic_preserves_sbadmin_field_metadata(self):
        widget = _DashboardWidget()
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(configuration=SBAdminRoleConfiguration())

        widget.init_view_dynamic(request, request_data=request.request_data)

    def test_dashboard_list_widget_uses_list_action_script_id(self):
        widget = _StandaloneDashboardWidget()
        request = self.factory.get("/dashboard/widget/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="price-list-1",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        request.LANGUAGE_CODE = "en"
        widget.init_view_dynamic(request, request_data=request.request_data)

        context = widget.get_widget_context_data(request)
        content_context = context["content_context"]

        self.assertEqual(widget.template_name, "sb_admin/dashboard/list_widget.html")
        self.assertEqual(
            content_context["tabulator_definition_script_id"],
            "embedded_dashboard_widget-tabulator-definition",
        )
        self.assertTrue(content_context["show_tabulator_header_controls"])
        self.assertFalse(content_context["filters_open_by_default"])
        self.assertTrue(
            content_context["tabulator_definition"]["tableAjaxUrl"].endswith(
                "/embedded_dashboard_widget/action_list_json/template/price-list-1/"
            )
        )

    def test_dashboard_list_widget_exposes_header_rendering_flags(self):
        widget = _StandaloneNoHeaderDashboardWidget()
        request = self.factory.get("/dashboard/widget/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="price-list-1",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        request.LANGUAGE_CODE = "en"
        widget.init_view_dynamic(request, request_data=request.request_data)

        content_context = widget.get_widget_context_data(request)["content_context"]

        self.assertFalse(content_context["show_tabulator_header_controls"])
        self.assertTrue(content_context["filters_open_by_default"])
        self.assertEqual(content_context["search_fields"], ("display_name",))

    def test_dashboard_list_widget_renders_list_actions_inside_widget(self):
        widget = _StandaloneNoHeaderDashboardWidget()
        request = self.factory.get("/dashboard/widget/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="price-list-1",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        request.LANGUAGE_CODE = "en"
        widget.init_view_dynamic(request, request_data=request.request_data)

        html = render_to_string(
            widget.template_name,
            widget.get_widget_context_data(request),
            request=request,
        )

        search_index = html.index(
            'id="embedded_no_header_dashboard_widget-sb_admin_full_search"'
        )
        action_index = html.index("action_xlsx_export/__all__/price-list-1/")
        self.assertLess(search_index, action_index)
        self.assertIn("btn btn-only-icon", html)
        self.assertIn("action_xlsx_export/__all__/price-list-1/", html)
        self.assertIn("dropdown-menu", html)

    def test_render_registered_standalone_widget_clones_request_data_for_widget(self):
        widget = _RenderedRegisteredWidget()
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SimpleNamespace(view_map={"registered_widget": widget}),
            view="parent_view",
            action="detail",
            object_id="parent_object",
            selected_view="parent_selected_view",
        )

        result = render_registered_standalone_widget(
            request,
            view_id="registered_widget",
            object_id="child_object",
        )

        self.assertEqual(str(result), "<div>Rendered widget</div>")
        self.assertIs(widget.initialized_request, widget.render_request)
        self.assertIsNot(widget.initialized_request, request)
        self.assertIsNot(widget.initialized_request_data, request.request_data)
        self.assertEqual(widget.initialized_request_data.view, "registered_widget")
        self.assertEqual(widget.initialized_request_data.action, Action.LIST.value)
        self.assertEqual(widget.initialized_request_data.object_id, "child_object")
        self.assertIs(widget.initialized_request_data.selected_view, widget)
        self.assertEqual(request.request_data.view, "parent_view")
        self.assertEqual(request.request_data.object_id, "parent_object")
