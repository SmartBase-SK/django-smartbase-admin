from types import SimpleNamespace

from django.contrib import admin
from django.contrib.admin.helpers import Fieldset
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.engine.const import (
    FILTER_DATA_NAME,
    IGNORE_LIST_SELECTION,
    PARENT_FILTER_DATA_NAME,
)
from django_smartbase_admin.engine.dashboard import (
    SbAdminCalendarWidget,
    SBAdminDashboardChartWidget,
    SBAdminDashboardGroupWidget,
    SBAdminDashboardHtmlWidget,
    SBAdminDashboardListWidget,
    SBAdminDashboardWidget,
)
from django_smartbase_admin.engine.dynamic_forms import SBDynamicRegion
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

urlpatterns = [path("", sb_admin_site.urls)]


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


class _CachedParentScopedWidget(SBAdminDashboardWidget):
    widget_id = "cached_parent_scoped_widget"
    cache_enabled = True

    def get_data(self, request):
        return {"object_id": request.request_data.object_id}


class _DashboardGroupSubWidget(SBAdminDashboardWidget):
    template_name = "sb_admin/blank_base.html"
    name = "Sub widget"

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def get_data(self, request):
        return {"value": 1}


class _DashboardHtmlSubWidget(SBAdminDashboardHtmlWidget):
    name = "HTML sub widget"

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def get_html(self, request):
        return "<p>Rendered HTML</p>"


class _DashboardGroupWidget(SBAdminDashboardGroupWidget):
    widget_id = "dashboard_group_widget"
    name = "Group widget"
    sub_widgets = [
        _DashboardGroupSubWidget(),
        _DashboardGroupSubWidget(),
    ]

    def get_action_url(self, action, modifier="template", object_id=None):
        return f"/{self.get_id()}/{action}/{modifier}/"

    def has_view_or_change_permission(self, request, obj=None):
        return True


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


class FieldsetWidgetTestModel(models.Model):
    username = models.CharField(max_length=150)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class _DashboardGroupChartSubWidget(SBAdminDashboardChartWidget):
    widget_id = "chart_sub_widget"
    model = FieldsetWidgetTestModel
    chart_type = "line"
    x_axis_annotate = F("username")

    def has_view_or_change_permission(self, request, obj=None):
        return True


class _DashboardChartGroupWidget(_DashboardGroupWidget):
    sub_widgets = [_DashboardGroupChartSubWidget()]


class _DashboardParentWidget(SBAdminDashboardWidget):
    widget_id = "dashboard_parent_widget"
    sub_widgets = [_DashboardGroupChartSubWidget()]

    def get_action_url(self, action, modifier="template", object_id=None):
        return f"/{self.get_id()}/{action}/{modifier}/"

    def has_view_or_change_permission(self, request, obj=None):
        return True


class _DashboardListGroupWidget(_DashboardGroupWidget):
    sub_widgets = [_StandaloneDashboardWidget()]


class _DashboardParentFilterListWidget(_StandaloneDashboardWidget):
    dashboard_filter_data = None

    def get_filter_from_dashboard_filter(self, request, dashboard_filter_data):
        self.dashboard_filter_data = dashboard_filter_data
        return Q()


class _DashboardParentFilterListGroupWidget(_DashboardGroupWidget):
    sub_widgets = [_DashboardParentFilterListWidget()]


class _DashboardHtmlGroupWidget(_DashboardGroupWidget):
    sub_widgets = [_DashboardHtmlSubWidget()]


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


class _DynamicRegionWidgetAdmin(_WidgetAdmin):
    sbadmin_fieldsets = [
        (
            "Profile",
            {
                "fields": [
                    SBDynamicRegion(
                        name="profile_region",
                        fields=("username", _RegisteredAdminWidget),
                    )
                ],
            },
        )
    ]

    def get_action_url(self, action, modifier="template", object_id=None):
        kwargs = self.get_action_url_kwargs(action, modifier, object_id)
        url = f"/{kwargs['view']}/{kwargs['action']}/{kwargs['modifier']}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url


class _ParentObjectListWidget(_StandaloneDashboardWidget):
    widget_id = "parent_object_list_widget"


class _ParentScopedChartWidget(SBAdminDashboardChartWidget):
    widget_id = "parent_scoped_chart_widget"
    model = FieldsetWidgetTestModel
    path_to_parent_instance_id = "id"
    x_axis_annotate = F("username")

    def get_action_url(self, action, modifier="template", object_id=None):
        kwargs = self.get_action_url_kwargs(action, modifier, object_id)
        url = f"/{kwargs['view']}/{kwargs['action']}/{kwargs['modifier']}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

    def has_view_or_change_permission(self, request, obj=None):
        return True


class _CustomParentScopedListWidget(_StandaloneDashboardWidget):
    widget_id = "custom_parent_scoped_list_widget"
    model = FieldsetWidgetTestModel

    def filter_queryset_by_parent_instance_ids(
        self, request, queryset, parent_instance_ids
    ):
        self.filtered_parent_instance_ids = list(parent_instance_ids)
        return queryset.filter(id__in=parent_instance_ids)


@override_settings(ROOT_URLCONF=__name__)
class TestSBAdminDashboardListWidget(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def init_dashboard_widget_static(self, widget):
        configuration = SimpleNamespace(view_map={})
        widget.init_widget_static(configuration)
        return configuration

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

    def test_dashboard_media_uses_object_specific_widget_views(self):
        class _ObjectSpecificDashboardView(SBAdminDashboardView):
            def get_widget_views(self, request, object_id=None):
                if object_id == "price-list-1":
                    return [SBAdminDashboardChartWidget()]
                return [_StandaloneDashboardWidget()]

            def get_global_context(self, request):
                return {}

        view = _ObjectSpecificDashboardView(title="Dashboard")
        request = self.factory.get("/dashboard/")

        response = view.dashboard(request, None, object_id="price-list-1")
        media_html = str(response.context_data["dashboard_media"])

        self.assertIsInstance(
            response.context_data["direct_sub_views"][0],
            SBAdminDashboardChartWidget,
        )
        self.assertIn("sb_admin/dist/chart.js", media_html)
        self.assertNotIn("sb_admin/dist/table.js", media_html)

    def test_dashboard_widgets_use_index_based_ids(self):
        configuration = SimpleNamespace(view_map={})
        view = SBAdminDashboardView(
            widgets=[_DashboardWidget(), _StandaloneDashboardWidget()]
        )

        view.init_view_static(configuration, None, AdminSite())

        self.assertEqual(view.widget_views[0].get_id(), "dashboard_0")
        self.assertEqual(view.widget_views[1].get_id(), "dashboard_1")
        self.assertIs(configuration.view_map["dashboard_0"], view.widget_views[0])
        self.assertIs(configuration.view_map["dashboard_1"], view.widget_views[1])

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
        admin_view = _FieldsetWidgetAdmin(FieldsetWidgetTestModel, AdminSite())
        admin_view.init_view_static(configuration, FieldsetWidgetTestModel, AdminSite())
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

    def test_dynamic_regions_can_place_widgets_by_class(self):
        configuration = SimpleNamespace(view_map={})
        admin_view = _DynamicRegionWidgetAdmin(FieldsetWidgetTestModel, AdminSite())
        admin_view.init_view_static(configuration, FieldsetWidgetTestModel, AdminSite())
        request = self.factory.get("/admin/auth/user/1/change/")

        fieldsets = admin_view.get_fieldsets(request)

        self.assertEqual(fieldsets[0][1]["fields"], ["username"])

        form_class = admin_view.get_form(request)
        form = form_class()
        widget = admin_view.widget_views[0]
        region = admin_view.sbadmin_fieldsets[0][1]["fields"][0]
        region_context = form.get_dynamic_region_context(region, request)

        self.assertEqual(region_context.fieldset.fields, ("username",))
        self.assertEqual(region_context.state.active_fields, ("username",))
        self.assertEqual(
            region_context.state.active_layout,
            ("username", _RegisteredAdminWidget),
        )
        self.assertEqual(
            region_context.fieldset_layout[0]["fieldset"].fields,
            ("username",),
        )
        self.assertIs(region_context.fieldset_layout[1]["widget"], widget)

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

    def test_dashboard_list_widget_uses_request_object_id_for_selection_actions(self):
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

        actions = widget.get_sbadmin_list_selection_actions_processed(request)

        self.assertTrue(
            actions[0].url.endswith(
                "/parent_object_list_widget/action_xlsx_export/template/parent-object/"
            )
        )
        self.assertTrue(
            actions[1].url.endswith(
                "/parent_object_list_widget/action_bulk_delete/template/parent-object/"
            )
        )

    def test_dashboard_widget_filters_queryset_by_parent_request(self):
        widget = _ParentScopedChartWidget()
        request = self.factory.get("/admin/auth/user/1/change/")
        request.request_data = SimpleNamespace(object_id="1")

        queryset = widget._filter_queryset_by_parent_request(
            request, FieldsetWidgetTestModel.objects.all()
        )

        self.assertEqual(queryset.query.where.children[0].rhs, [1])

    def test_dashboard_chart_widget_uses_request_object_id_for_ajax_url(self):
        widget = _ParentScopedChartWidget()
        request = self.factory.get("/admin/auth/user/1/change/")
        request.request_data = SimpleNamespace(object_id="parent-object")

        context = widget.get_widget_context_data(request)

        self.assertTrue(
            context["ajax_url"].endswith(
                "/parent_scoped_chart_widget/action_get_data/template/parent-object/"
            )
        )

    def test_dashboard_widget_cache_key_includes_request_object_id(self):
        cache.clear()
        widget = _CachedParentScopedWidget()
        base_request_data = {
            "global_filter": {},
            "request_get": {},
            "request_post": {},
            "user": SimpleNamespace(id=1),
        }
        first_request = self.factory.get("/admin/auth/user/1/change/")
        first_request.request_data = SimpleNamespace(
            **base_request_data,
            object_id="parent-1",
        )
        second_request = self.factory.get("/admin/auth/user/2/change/")
        second_request.request_data = SimpleNamespace(
            **base_request_data,
            object_id="parent-2",
        )

        self.assertEqual(
            widget.get_cached_data(first_request), {"object_id": "parent-1"}
        )
        self.assertEqual(
            widget.get_cached_data(second_request), {"object_id": "parent-2"}
        )

    def test_dashboard_group_widget_initializes_existing_sub_widgets(self):
        widget = _DashboardGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id=None,
        )

        widget.init_view_dynamic(request, request_data=request.request_data)
        sub_widgets = widget.get_sub_widgets()

        self.assertEqual(sub_widgets[0].get_id(), "dashboard_group_widget_0")
        self.assertEqual(sub_widgets[1].get_id(), "dashboard_group_widget_1")
        self.assertIs(sub_widgets[0].parent_view, widget)
        self.assertEqual(
            widget.get_data(request),
            {
                "sub_widget": {
                    "dashboard_group_widget_0": {"value": 1},
                    "dashboard_group_widget_1": {"value": 1},
                }
            },
        )

    def test_dashboard_group_widget_template_owns_single_parent_ajax_call(self):
        widget = _DashboardGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id=None,
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        html = render_to_string(
            widget.template_name,
            widget.get_widget_context_data(request),
            request=request,
        )

        self.assertIn('data-dashboard-group-id="dashboard_group_widget"', html)
        self.assertIn('data-filter-form-id="dashboard_group_widget-filter-form"', html)
        self.assertIn(
            'data-ajax-url="/dashboard_group_widget/action_get_data/template/"', html
        )
        self.assertIn("window.SBAdminInitDashboardGroups()", html)
        self.assertNotIn("registerChart", html)
        self.assertNotIn("setTimeout", html)

    def test_dashboard_group_widget_renders_default_chart_subwidget_without_standalone_ajax(
        self,
    ):
        widget = _DashboardChartGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id=None,
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        html = render_to_string(
            widget.template_name,
            widget.get_widget_context_data(request),
            request=request,
        )

        self.assertIn('"parentWidgetId": "dashboard_group_widget"', html)
        self.assertIn('"formId": "dashboard_group_widget_0-filter-form"', html)
        self.assertIn('"widgetId": "dashboard_group_widget_0"', html)
        self.assertNotIn(
            '"ajaxUrl": "/dashboard_group_widget_0/action_get_data/template/"', html
        )
        self.assertIn("new window.SBAdminChartClass", html)

    def test_dashboard_parent_widget_keeps_chart_subwidget_own_ajax(self):
        widget = _DashboardParentWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id=None,
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        sub_widget = widget.get_sub_widgets()[0]
        html = render_to_string(
            sub_widget.template_name,
            sub_widget.get_widget_context_data(request),
            request=request,
        )

        self.assertNotIn('"parentWidgetId": "dashboard_parent_widget"', html)
        self.assertIn('"formId": "dashboard_parent_widget-filter-form"', html)
        self.assertIn("dashboard_parent_widget_0/action_get_data/template/", html)

    def test_dashboard_group_widget_keeps_list_subwidget_table_ajax(self):
        widget = _DashboardListGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.LANGUAGE_CODE = "en"
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="parent-object",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        html = render_to_string(
            widget.template_name,
            widget.get_widget_context_data(request),
            request=request,
        )

        self.assertIn("dashboard_group_widget_0-table", html)
        self.assertIn(
            "/dashboard_group_widget_0/action_list_json/template/parent-object/",
            html,
        )
        self.assertNotIn(
            "/dashboard_group_widget/action_list_json/template/parent-object/",
            html,
        )
        tabulator_definition = widget.get_sub_widgets()[0].get_tabulator_definition(
            request
        )
        self.assertEqual(
            tabulator_definition["parentWidgetId"], "dashboard_group_widget"
        )
        self.assertIn("dashboardParentFilterModule", tabulator_definition["modules"])
        self.assertEqual(
            widget.get_data(request),
            {"sub_widget": {"dashboard_group_widget_0": {}}},
        )

    def test_dashboard_list_widget_passes_parent_filter_data_to_filter_hook(self):
        widget = _DashboardParentFilterListGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.LANGUAGE_CODE = "en"
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="parent-object",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
            global_filter_instance=[],
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )
        widget.init_view_dynamic(request, request_data=request.request_data)
        list_widget = widget.get_sub_widgets()[0]

        action = SBAdminListAction(
            list_widget,
            request,
            all_params={
                "dashboard_group_widget_0": {PARENT_FILTER_DATA_NAME: {"shipper": "42"}}
            },
        )
        action.get_filter_from_request()

        self.assertEqual(list_widget.dashboard_filter_data, {"shipper": "42"})

    def test_dashboard_group_widget_updates_html_subwidget_from_parent_data(self):
        widget = _DashboardHtmlGroupWidget()
        self.init_dashboard_widget_static(widget)
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id=None,
        )
        widget.init_view_dynamic(request, request_data=request.request_data)

        html = render_to_string(
            widget.template_name,
            widget.get_widget_context_data(request),
            request=request,
        )
        data = widget.get_data(request)

        self.assertIn("SBAdminRegisterDashboardSubWidget", html)
        self.assertIn("onData: function(data)", html)
        self.assertIn('widgetId: "dashboard_group_widget_0"', html)
        self.assertIn(
            "Rendered HTML", data["sub_widget"]["dashboard_group_widget_0"]["html"]
        )

    def test_dashboard_list_widget_uses_batch_parent_filter_hook(self):
        widget = _CustomParentScopedListWidget()
        request = self.factory.get("/admin/auth/user/1/change/")
        request.request_data = SimpleNamespace(
            configuration=SBAdminRoleConfiguration(),
            request_get={},
            request_method="GET",
            object_id="7",
            user=SimpleNamespace(first_name="", last_name="", username="tester"),
            global_filter_instance=[],
        )
        request.user = SimpleNamespace(
            is_anonymous=True, has_perm=lambda _permission: True
        )

        widget.get_queryset(request)

        self.assertEqual(widget.filtered_parent_instance_ids, ["7"])

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
