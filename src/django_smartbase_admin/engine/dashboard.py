import pickle
from copy import copy, deepcopy
from datetime import timedelta

from django.core.cache import cache
from django.db import models
from django.db.models import QuerySet
from django.db.models.functions import TruncMonth, TruncDay, TruncWeek, TruncYear
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import OBJECT_ID_PLACEHOLDER
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import (
    ChoiceFilterWidget,
    DateFilterWidget,
    RadioChoiceFilterWidget,
)
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.utils import to_list


class SBAdminDashboardWidget(SBAdminView):
    template_name = None
    name = None
    widget_id = None
    annotates = None
    filters = None
    settings = None
    sub_widgets = None
    global_filter_data_map = None
    cache_enabled = False
    SUB_WIDGET_NAME_SUFFIX = "_sub_widget"

    def __init__(
        self,
        template_name=None,
        name=None,
        model=None,
        annotates=None,
        filters=None,
        settings=None,
        sub_widgets=None,
        global_filter_data_map=None,
    ) -> None:
        super().__init__()
        self.template_name = self.template_name or template_name
        self.name = self.name or name
        self.model = self.model or model
        self.annotates = self.annotates or annotates
        self.filters = self.filters or filters or []
        self.settings = self.settings or settings or []
        self.sub_widgets = self.sub_widgets or sub_widgets or []
        self.global_filter_data_map = (
            self.global_filter_data_map or global_filter_data_map
        )

    def init_widget_static(self, configuration):
        self.view_id = self.widget_id
        for filter in self.get_filters():
            filter.init_field_static(self, configuration)
        for setting in self.get_settings():
            setting.init_field_static(self, configuration)

    def get_id(self):
        return self.widget_id

    def get_filters(self):
        return self.filters

    def get_settings(self):
        return self.settings

    def get_ajax_url(self):
        return self.get_action_url("action_get_data")

    def action_get_data(self, request, modifier):
        return JsonResponse(data={"data": self.get_cached_data(request)})

    def get_widget_context_data(self, request):
        return {
            "widget_id": self.get_id(),
            "ajax_url": self.get_ajax_url,
            "filters": self.get_filters(),
            "settings": self.get_settings(),
            "sub_widgets": self.get_sub_widgets(),
            "request": request,
        }

    def get_sub_widgets(self):
        return self.sub_widgets

    def get_template_name(self):
        return self.template_name

    def render(self, request):
        return render_to_string(
            self.get_template_name(), context=self.get_widget_context_data(request)
        )

    def get_filters_from_request(self, request):
        return SBAdminViewService.get_filter_from_request(
            request, self.get_filters(), request.request_data.request_get
        )

    def get_settings_from_request(self, request):
        settings = {}
        for setting in self.get_settings():
            settings[setting.name] = request.request_data.request_get.get(
                setting.name, None
            )
        return settings

    def get_data(self, request):
        raise NotImplementedError

    def get_cached_data(self, request):
        cache_key = f"{SBAdminViewService.get_cache_key_for_user(request.request_data)}_{self.get_id()}"
        return_data = None
        if self.cache_enabled:
            return_data = cache.get(cache_key)
        if return_data:
            return return_data
        return_data = self.get_data(request)
        if self.cache_enabled:
            cache.set(cache_key, return_data, timeout=60 * 60)
        return return_data

    def get_active_sub_widget(self, request):
        sub_widgets = self.get_sub_widgets()
        for sub_widget in sub_widgets:
            if sub_widget.is_active(request):
                return sub_widget
        return next(iter(sub_widgets), None)


class SBAdminChartAggregateSubWidget(object):
    title = None
    aggregate = None
    template_name = "sb_admin/dashboard/chart_aggregate_sub_widget.html"
    sub_widget_id = None
    python_formatter = None
    parent_view = None

    def __init__(
        self, title=None, aggregate=None, python_formatter=None, template_name=None
    ) -> None:
        super().__init__()
        self.title = self.title or title
        self.aggregate = self.aggregate or aggregate
        self.python_formatter = self.python_formatter or python_formatter
        self.template_name = self.template_name or template_name

    def get_aggregate(self, request):
        return self.aggregate

    def get_parent_queryset_override(self, request):
        return None

    def get_data(self, request, base_qs):
        value = (
            base_qs.aggregate(result=self.get_aggregate(request)).get("result", 0) or 0
        )
        return {
            "raw_value": value,
            "formatted_value": (
                self.python_formatter(self, request, value)
                if self.python_formatter
                else value
            ),
        }

    def init_sub_widget_dynamic(self, sub_widget_id, parent_view):
        self.sub_widget_id = sub_widget_id
        self.parent_view = parent_view

    def get_id(self):
        return self.sub_widget_id

    def is_active(self, request):
        active_sub_widget_id = request.request_data.request_get.get(
            f"{self.parent_view.get_id()}{self.parent_view.SUB_WIDGET_NAME_SUFFIX}",
            None,
        )
        return active_sub_widget_id == self.get_id()

    def get_context_data(self, request):
        active_widget = self.parent_view.get_active_sub_widget(request)
        return {"sub_widget": self, "is_active": active_widget == self}

    def render(self, request):
        return render_to_string(self.template_name, self.get_context_data(request))


class SBAdminDashboardChartWidget(SBAdminDashboardWidget):
    template_name = "sb_admin/dashboard/chart_widget.html"
    x_axis_annotate = None
    y_axis_annotate = None
    chart_type = None
    order_by = None

    def __init__(
        self,
        name=None,
        template_name=None,
        model=None,
        annotates=None,
        filters=None,
        settings=None,
        x_axis_annotate=None,
        y_axis_annotate=None,
        order_by=None,
        sub_widgets=None,
        global_filter_data_map=None,
    ) -> None:
        super().__init__(
            template_name=template_name,
            name=name,
            model=model,
            annotates=annotates,
            filters=filters,
            settings=settings,
            sub_widgets=sub_widgets,
            global_filter_data_map=global_filter_data_map,
        )
        self.order_by = self.order_by or order_by
        self.x_axis_annotate = self.x_axis_annotate or x_axis_annotate
        self.y_axis_annotate = self.y_axis_annotate or y_axis_annotate

    def get_widget_context_data(self, request):
        context = super().get_widget_context_data(request)
        context["chart_type"] = self.chart_type
        return context

    def get_x_axis_annotate(self, request):
        return self.x_axis_annotate

    def get_y_axis_annotate(self, request):
        active_sub_widget = self.get_active_sub_widget(request)
        if active_sub_widget:
            return active_sub_widget.get_aggregate(request)
        return self.y_axis_annotate

    def get_order_by(self, request):
        return to_list(self.order_by)

    def process_label(self, request, label, data, labels, dataset_data):
        return label

    def process_data(self, request, label, data, labels, dataset_data):
        return data

    def get_annotates(self, request):
        return SBAdminViewService.get_annotates(
            self.model,
            [field.field for field in self.get_filters()],
            self.get_filters(),
        )

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        filters = self.get_filters_from_request(request)
        qs = qs.annotate(**self.get_annotates(request)).filter(filters)
        return qs

    def get_data_queryset(self, request):
        active_sub_widget = self.get_active_sub_widget(request)
        qs = None
        if active_sub_widget:
            qs = active_sub_widget.get_parent_queryset_override(request)
        if not isinstance(qs, QuerySet):
            qs = self.get_queryset(request)
        return qs

    def get_sub_widget_queryset(self, request, sub_widget):
        qs = sub_widget.get_parent_queryset_override(request)
        if not isinstance(qs, QuerySet):
            qs = self.get_queryset(request)
        return qs

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        init_result = super().init_view_dynamic(request, request_data, **kwargs)
        for idx, sub_widget in enumerate(self.sub_widgets):
            sub_widget.init_sub_widget_dynamic(f"{self.get_id()}_{idx}", self)
        return init_result

    def get_data(self, request):
        data_qs = self.get_data_queryset(request)
        data = list(
            (
                data_qs.annotate(x_axis=self.get_x_axis_annotate(request))
                .values("x_axis")
                .annotate(y_axis=self.get_y_axis_annotate(request))
            )
            .values("x_axis", "y_axis")
            .order_by(*self.get_order_by(request))
        )

        labels = []
        dataset_data = []

        for item in data:
            labels.append(
                self.process_label(
                    request,
                    item["x_axis"],
                    item["y_axis"],
                    labels,
                    dataset_data,
                )
            )
            dataset_data.append(
                self.process_data(
                    request,
                    item["x_axis"],
                    item["y_axis"],
                    labels,
                    dataset_data,
                )
            )

        sub_widget_data = {}
        for sub_widget in self.get_sub_widgets():
            sub_widget_qs = self.get_sub_widget_queryset(request, sub_widget)
            sub_widget_data[sub_widget.get_id()] = sub_widget.get_data(
                request, sub_widget_qs
            )
        return_data = {
            "main": {
                "labels": labels,
                "datasets": [
                    {
                        "label": self.name,
                        "data": dataset_data,
                        **self.get_dataset_options(request),
                    }
                ],
            },
            "sub_widget": sub_widget_data,
        }
        return return_data

    def get_dataset_options(self, request):
        return {
            "order": 2,
            "backgroundColorGradientStart": "rgba(0, 159, 167, 0)",
            "backgroundColor": "rgba(0, 159, 167, 0.5)",
            "borderColor": "#009FA7",
            "pointHoverRadius": 6,
            "pointHoverBorderWidth": 5,
            "pointHoverBackgroundColor": "#ffffff",
            "pointBorderColor": "#009FA7",
            "pointRadius": 3,
            "pointBackgroundColor": "#009FA7",
            "fill": True,
        }


class SBAdminDashboardChartWidgetByDate(SBAdminDashboardChartWidget):
    date_annotate_field = None
    date_resolutions = None
    cumulative_data = None

    class DateResolutionsOptions(models.TextChoices):
        DATE_RESOLUTION_YEAR = "Year", _("Year")
        DATE_RESOLUTION_MONTH = "Month", _("Month")
        DATE_RESOLUTION_WEEK = "Week", _("Week")
        DATE_RESOLUTION_DAY = "Day", _("Day")

    class CompareOptions(models.TextChoices):
        COMPARE_PREVIOUS = "previous", _("Previous Period")
        COMPARE_PREVIOUS_YOY = "previous-yoy", _("Previous Year")

    RESOLUTION_KEY = "__resolution__"
    COMPARE_KEY = "__compare__"
    default_date_resolution = DateResolutionsOptions.DATE_RESOLUTION_MONTH

    def __init__(
        self,
        date_annotate_field=None,
        date_resolutions=None,
        cumulative_data=None,
        name=None,
        template_name=None,
        model=None,
        annotates=None,
        filters=None,
        settings=None,
        y_axis_annotate=None,
        sub_widgets=None,
        global_filter_data_map=None,
    ) -> None:
        self.date_annotate_field = self.date_annotate_field or date_annotate_field
        self.date_resolutions = (
            self.date_resolutions or date_resolutions or self.DateResolutionsOptions
        )
        self.cumulative_data = self.cumulative_data or cumulative_data
        if self.cumulative_data is None:
            self.cumulative_data = False
        correct_resolutions = all(
            elem in self.DateResolutionsOptions.values for elem in self.date_resolutions
        )
        if not correct_resolutions:
            raise RuntimeError(
                f"Correct date_resolutions selection {self.date_resolutions}. Available choices {self.DateResolutionsOptions.values}."
            )
        x_axis_annotate = None
        order_by = "x_axis"
        settings = [
            *settings,
            SBAdminField(
                name=self.RESOLUTION_KEY,
                title=_("Resolution"),
                filter_widget=RadioChoiceFilterWidget(
                    choices=self.DateResolutionsOptions.choices,
                    default_value=self.default_date_resolution,
                ),
            ),
            SBAdminField(
                title=_("Compare"),
                name=f"{self.COMPARE_KEY}",
                filter_widget=RadioChoiceFilterWidget(
                    choices=self.CompareOptions.choices,
                    default_value=self.CompareOptions.values[0],
                ),
            ),
        ]
        filters = self.filters or filters or []
        shortcuts = self.get_date_widget_shortcuts()
        filters = [
            SBAdminField(
                title=_("Date"),
                name=self.date_annotate_field,
                filter_widget=DateFilterWidget(
                    shortcuts=shortcuts,
                    default_value_shortcut_index=self.get_default_shortcut_index(),
                ),
            ),
            *filters,
        ]
        super().__init__(
            name=name,
            template_name=template_name,
            model=model,
            annotates=annotates,
            filters=filters,
            settings=settings,
            x_axis_annotate=x_axis_annotate,
            y_axis_annotate=y_axis_annotate,
            order_by=order_by,
            sub_widgets=sub_widgets,
            global_filter_data_map=global_filter_data_map,
        )

    def get_date_widget_shortcuts(self):
        return [
            {"value": [-30, 0], "label": _("Last 30 days")},
            {
                "value": [-91, 0],
                "label": _("Last Quarter"),
            },
            {
                "value": [-365, 0],
                "label": _("Last Year"),
            },
        ]

    def get_default_shortcut_index(self):
        return 1

    def get_current_resolution(self, request):
        return (
            self.get_settings_from_request(request)[self.RESOLUTION_KEY]
            or self.default_date_resolution
        )

    def get_x_axis_annotate(self, request):
        resolution = self.get_current_resolution(request)
        if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_YEAR:
            return TruncYear(self.date_annotate_field)
        if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_MONTH:
            return TruncMonth(self.date_annotate_field)
        if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_WEEK:
            return TruncWeek(self.date_annotate_field)
        if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_DAY:
            return TruncDay(self.date_annotate_field)

    def process_label(self, request_data, label, data, labels, dataset_data):
        try:
            resolution = self.get_current_resolution(request_data)
            if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_YEAR:
                return label.strftime("%Y")
            if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_MONTH:
                return label.strftime("%m/%y")
            if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_WEEK:
                return label.strftime("%-W/%y")
            if resolution == self.DateResolutionsOptions.DATE_RESOLUTION_DAY:
                return label.strftime("%x")
        except:
            return "<empty>"

    def process_data(self, request_data, label, data, labels, dataset_data):
        if self.cumulative_data and len(dataset_data) > 0:
            return data + dataset_data[-1]
        return data

    def get_compare_dataset(self, base_qs, request):
        data = list(
            (
                base_qs.annotate(x_axis=self.get_x_axis_annotate(request))
                .values("x_axis")
                .annotate(y_axis=self.get_y_axis_annotate(request))
            )
            .values("x_axis", "y_axis")
            .order_by(*self.get_order_by(request))
        )
        dataset_data = []
        for item in data:
            dataset_data.append(
                self.process_data(
                    request, item["x_axis"], item["y_axis"], None, dataset_data
                )
            )
        return dataset_data

    def get_data(self, request):
        request_data = request.request_data
        compare = self.get_settings_from_request(request).get(self.COMPARE_KEY, None)
        data = super().get_data(request)
        if compare:
            request_copy = copy(request)
            request_data_modified_date_filter = copy(request_data)
            request_copy.request_data = request_data_modified_date_filter
            request_data_modified_date_filter.request_get._mutable = True
            date_range, is_range = DateFilterWidget.get_date_or_range_from_value(
                request_data_modified_date_filter.request_get.get(
                    self.date_annotate_field
                )
            )
            date_range_compare = date_range
            if compare == self.CompareOptions.COMPARE_PREVIOUS:
                period_length = (date_range_compare[1] - date_range_compare[0]).days + 1
                date_range_compare[0] = date_range_compare[0] - timedelta(
                    days=period_length
                )
                date_range_compare[1] = date_range_compare[1] - timedelta(
                    days=period_length
                )
            if compare == self.CompareOptions.COMPARE_PREVIOUS_YOY:
                date_range_compare[0] = date_range_compare[0].replace(
                    year=date_range_compare[0].year - 1
                )
                date_range_compare[1] = date_range_compare[1].replace(
                    year=date_range_compare[1].year - 1
                )
            request_data_modified_date_filter.request_get[self.date_annotate_field] = (
                DateFilterWidget.get_value_from_date_or_range(date_range_compare)
            )
            queryset_with_modified_date = self.get_data_queryset(request_copy)

            sub_widget_data = {}
            for sub_widget in self.get_sub_widgets():
                subwidget_queryset_with_modified_date = self.get_sub_widget_queryset(
                    request_copy, sub_widget
                )
                sub_widget_data[sub_widget.get_id()] = sub_widget.get_data(
                    request, subwidget_queryset_with_modified_date
                )
            compare_dataset = self.get_compare_dataset(
                queryset_with_modified_date, request
            )
            data["main"]["datasets"].append(
                {
                    "label": _("Compare"),
                    "data": compare_dataset,
                    **self.get_compare_dataset_options(request_data),
                }
            )
            data["sub_widget_compare"] = sub_widget_data

        return data

    def get_compare_dataset_options(self, request_data):
        return {
            "order": 1,
            "backgroundColor": "transparent",
            "borderColor": "#F18F01",
            "pointHoverRadius": 6,
            "pointHoverBorderWidth": 5,
            "pointHoverBackgroundColor": "#ffffff",
            "pointBorderColor": "#F18F01",
            "pointRadius": 3,
            "pointBackgroundColor": "#F18F01",
            "fill": True,
            "borderDash": [10, 5],
            "borderWidth": 2,
        }


class SBAdminDashboardLineChartWidgetByDate(SBAdminDashboardChartWidgetByDate):
    chart_type = "line"


class SBAdminDashboardListWidget(SBAdminBaseListView, SBAdminDashboardWidget):
    template_name = "sb_admin/dashboard/list_widget.html"
    cache_enabled = False
    sbadmin_table_history_enabled = False

    def __init__(
        self,
        list_display=None,
        sbadmin_list_display=None,
        list_per_page=None,
        template_name=None,
        name=None,
        model=None,
        annotates=None,
        filters=None,
        settings=None,
        sub_widgets=None,
        global_filter_data_map=None,
    ) -> None:
        super().__init__(
            template_name=template_name,
            name=name,
            model=model,
            annotates=annotates,
            filters=filters,
            settings=settings,
            sub_widgets=sub_widgets,
            global_filter_data_map=global_filter_data_map,
        )
        self.list_display = list_display or self.list_display
        self.sbadmin_list_display = sbadmin_list_display or self.sbadmin_list_display
        self.list_per_page = list_per_page or self.list_per_page

    def get_detail_url(self):
        return reverse(
            f"sb_admin:{self.get_model_path()}_change",
            kwargs={"object_id": OBJECT_ID_PLACEHOLDER},
        )

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        super().init_view_dynamic(request, request_data, **kwargs)
        self.init_fields_cache(
            self.get_list_display(request), request.request_data.configuration
        )

    def get_widget_context_data(self, request):
        context = super().get_widget_context_data(request)
        context.update(self.get_global_context(request))
        action = SBAdminListAction(self, request)
        data = action.get_template_data()
        context["content_context"] = data
        context["list_base_template"] = "sb_admin/blank_base.html"
        return context

    def get_tabulator_definition(self, request):
        tabulator_definition = super().get_tabulator_definition(request)
        tabulator_definition["modules"] = [
            "viewsModule",
            "tableParamsModule",
            "detailViewModule",
        ]
        return tabulator_definition
