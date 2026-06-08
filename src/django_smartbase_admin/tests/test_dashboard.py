from types import SimpleNamespace

from django.contrib import admin
from django.contrib.admin.helpers import Fieldset
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import F
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import render_to_string
from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.engine.const import FILTER_DATA_NAME, IGNORE_LIST_SELECTION
from django_smartbase_admin.engine.dashboard import (
    SbAdminCalendarWidget,
    SBAdminDashboardChartWidget,
    SBAdminDashboardWidget,
    SBAdminDashboardListWidget,
)
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView


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
        kwargs = self.get_action_url_kwargs(action, modifier, object_id)
        url = f"/{kwargs['view']}/{kwargs['action']}/{kwargs['modifier']}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

    @admin.display(description="Display name")
    def display_name(self, object_id, value, **kwargs):
        return value


class _StandaloneNoHeaderDashboardWidget(_StandaloneDashboardWidget):
    widget_id = "embedded_no_header_dashboard_widget"
    search_fields = ("display_name",)


class _RegisteredAdminWidget(SBAdminDashboardWidget):
    widget_id = "registered_admin_widget"

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        self.initialized_request = request
        self.initialized_request_data = request_data


class _WidgetAdmin(SBAdmin):
    widgets = [_RegisteredAdminWidget]
    sbadmin_fieldsets = [(None, {"fields": []})]

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def init_actions(self, request):
        pass


class _MissingWidgetIdWidget(SBAdminDashboardWidget):
    pass


class _MissingWidgetIdAdmin(_WidgetAdmin):
    widgets = [_MissingWidgetIdWidget]


class _FieldsetWidgetModel(models.Model):
    username = models.CharField(max_length=150)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class _FieldsetWidgetAdmin(_WidgetAdmin):
    sbadmin_fieldsets = [
        (
            "Profile",
            {
                "fields": ["username", _RegisteredAdminWidget],
                "classes": ["detail-view-right"],
            },
        )
    ]


class _ParentObjectListWidget(_StandaloneDashboardWidget):
    widget_id = "parent_object_list_widget"


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
        self.assertEqual(
            content_context["tabulator_header_template_name"],
            "sb_admin/actions/partials/tabulator_header_change_view_v1.html",
        )
        self.assertEqual(
            content_context["filters_template_name"],
            "sb_admin/dashboard/includes/list_widget_filters.html",
        )
        self.assertNotIn("filters_toolbar_after_search_template", content_context)
        self.assertNotIn("show_tabulator_header_controls", content_context)
        self.assertNotIn("filters_open_by_default", content_context)
        self.assertTrue(
            content_context["tabulator_definition"]["tableAjaxUrl"].endswith(
                "/embedded_dashboard_widget/action_list_json/template/price-list-1/"
            )
        )
        self.assertEqual(
            str(content_context["media"]).count("sb_admin/dist/table.js"), 1
        )

    def test_dashboard_list_widget_uses_change_view_header_template(self):
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

        self.assertEqual(
            content_context["tabulator_header_template_name"],
            "sb_admin/actions/partials/tabulator_header_change_view_v1.html",
        )
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

        self.assertNotIn("save-view-modal-button", html)
        self.assertNotIn("filters-collapse-button", html)
        self.assertIn(
            'id="filters-collapse" class="collapse max-sm:overflow-x-auto '
            'custom-scrollbar show"',
            html,
        )
        search_index = html.index(
            'id="embedded_no_header_dashboard_widget-sb_admin_full_search"'
        )
        action_index = html.index("action_xlsx_export/__all__/price-list-1/")
        self.assertLess(search_index, action_index)
        column_picker_index = html.index('xlink:href="#Column"')
        actions_button_index = html.index('xlink:href="#More"')
        self.assertLess(column_picker_index, actions_button_index)
        self.assertRegex(html, r'title="(Columns|Stĺpce)"')
        self.assertIn("btn btn-only-icon", html)
        self.assertIn("action_xlsx_export/__all__/price-list-1/", html)
        self.assertIn("dropdown-menu", html)
        self.assertNotIn("sb_admin/dist/table.js", html)

    def test_dashboard_collects_widget_media_once(self):
        view = SBAdminDashboardView()
        view.widget_views = [
            SBAdminDashboardChartWidget(),
            SBAdminDashboardChartWidget(),
            _StandaloneDashboardWidget(),
            _StandaloneDashboardWidget(),
            SbAdminCalendarWidget(),
        ]
        request = self.factory.get("/dashboard/")

        media_html = str(view.get_dashboard_media(request))

        self.assertEqual(media_html.count("sb_admin/dist/chart.js"), 1)
        self.assertEqual(media_html.count("sb_admin/dist/table.js"), 1)
        self.assertEqual(media_html.count("sb_admin/js/fullcalendar.min.js"), 1)
        self.assertEqual(media_html.count("sb_admin/dist/calendar.js"), 1)
        self.assertEqual(media_html.count("sb_admin/dist/calendar_style.css"), 1)

    def test_change_view_collects_widget_media_once(self):
        admin_view = _WidgetAdmin(User, AdminSite())
        admin_view.widget_views = [
            SBAdminDashboardChartWidget(),
            SBAdminDashboardChartWidget(),
            _StandaloneDashboardWidget(),
            _StandaloneDashboardWidget(),
        ]
        request = self.factory.get("/admin/auth/user/1/change/")

        media_html = str(admin_view.get_change_view_widget_media(request))

        self.assertEqual(media_html.count("sb_admin/dist/chart.js"), 1)
        self.assertEqual(media_html.count("sb_admin/dist/table.js"), 1)

    def test_dashboard_list_widget_xlsx_filename_uses_widget_name(self):
        widget = _StandaloneDashboardWidget(name="Ceny dopravy")
        request = self.factory.get("/dashboard/widget/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            modifier=IGNORE_LIST_SELECTION,
            object_id="price-list-1",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        request.LANGUAGE_CODE = "en"
        widget.init_view_dynamic(request, request_data=request.request_data)

        action = SBAdminListAction(widget, request, all_params={})
        action.get_excel_columns = lambda: []
        action.get_data = lambda **_kwargs: {"data": [], "last_page": 1}
        file_name = action.get_xlsx_data(request)[0]

        self.assertTrue(file_name.startswith("Ceny dopravy__"))
        self.assertNotIn("None__", file_name)

    def test_admin_widgets_register_with_parent_scoped_ids(self):
        configuration = SimpleNamespace(view_map={})
        admin_view = _WidgetAdmin(User, AdminSite())

        admin_view.init_view_static(configuration, User, AdminSite())

        widget = configuration.view_map["auth_user_registered_admin_widget"]
        self.assertEqual(widget.get_id(), "auth_user_registered_admin_widget")
        self.assertIs(configuration.view_map[widget.get_id()], widget)
        self.assertIs(widget.parent_view, admin_view)

    def test_admin_widgets_require_widget_id(self):
        configuration = SimpleNamespace(view_map={})
        admin_view = _MissingWidgetIdAdmin(User, AdminSite())

        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "_MissingWidgetIdWidget must define widget_id.",
        ):
            admin_view.init_view_static(configuration, User, AdminSite())

    def test_admin_widgets_initialize_with_parent_request(self):
        configuration = SimpleNamespace(view_map={})
        admin_view = _WidgetAdmin(User, AdminSite())
        admin_view.init_view_static(configuration, User, AdminSite())
        request = self.factory.get("/admin/auth/user/1/change/")
        request.request_data = SimpleNamespace(
            configuration=configuration,
            object_id="1",
            request_get={},
            request_method="GET",
            selected_view=admin_view,
            autocomplete_map={},
        )

        admin_view.init_view_dynamic(request, request.request_data)

        widget = configuration.view_map["auth_user_registered_admin_widget"]
        self.assertIs(widget.initialized_request, request)
        self.assertIs(widget.initialized_request_data, request.request_data)

    def test_fieldsets_can_place_widgets_by_class(self):
        configuration = SimpleNamespace(view_map={})
        admin_view = _FieldsetWidgetAdmin(_FieldsetWidgetModel, AdminSite())
        admin_view.init_view_static(configuration, _FieldsetWidgetModel, AdminSite())
        request = self.factory.get("/admin/auth/user/1/change/")

        fieldsets = admin_view.get_fieldsets(request)

        self.assertEqual(fieldsets[0][1]["fields"], ["username"])

        form_class = admin_view.get_form(request)
        form = form_class()
        widget = admin_view.widget_views[0]
        fieldset = Fieldset(
            form=form,
            name="Profile",
            fields=("username",),
            classes="detail-view-right",
            model_admin=admin_view,
        )

        fieldset_context = form.get_fieldset_context(fieldset, request)

        layout = fieldset_context["fieldset_layout"]
        self.assertEqual(layout[0]["fieldset"].fields, ("username",))
        self.assertIs(layout[1]["widget"], widget)

    def test_dashboard_list_widget_uses_request_object_id_for_embedded_urls(self):
        widget = _ParentObjectListWidget()
        request = self.factory.get("/admin/parent/1/change/")
        request.LANGUAGE_CODE = "en"
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            modifier=IGNORE_LIST_SELECTION,
            object_id="parent-object",
            selected_view=widget,
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        definition = widget.get_tabulator_definition(request)

        self.assertTrue(
            definition["tableAjaxUrl"].endswith(
                "/parent_object_list_widget/action_list_json/template/parent-object/"
            )
        )

    def test_list_action_reads_registered_view_params(self):
        widget = _ParentObjectListWidget()
        request = self.factory.get("/parent_object_list_widget/action_list_json/")
        request.LANGUAGE_CODE = "en"
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            modifier=IGNORE_LIST_SELECTION,
            object_id="manual-object",
            selected_view=widget,
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        action = SBAdminListAction(
            widget,
            request,
            all_params={
                "parent_object_list_widget": {FILTER_DATA_NAME: {"display_name": "Ada"}}
            },
        )

        self.assertEqual(action.filter_data, {"display_name": "Ada"})
