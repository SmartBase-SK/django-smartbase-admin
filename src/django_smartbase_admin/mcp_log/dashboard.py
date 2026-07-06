"""Dashboard over ``MCPRequestLog`` — branded "AI Assistant Module".

A calls-over-time line chart whose aggregate cards (Calls / Errors / duration /
volume) double as series selectors and share the chart's date-range filter,
plus a filterable recent-calls list. Registered via the project's
``SBAdminConfiguration.registered_views``; reachable at
``/sb-admin/aiassistantmodule/aiassistantmodule/template/``.
"""

from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Avg, Count, F, Q, Sum, TextField, Value
from django.db.models.functions import Coalesce
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.dashboard import (
    SBAdminChartAggregateSubWidget,
    SBAdminDashboardLineChartWidgetByDate,
    SBAdminDashboardListWidget,
)
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import BadgeType, format_badge
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    BooleanFilterWidget,
    DateFilterWidget,
    FromValuesAutocompleteWidget,
    RadioChoiceFilterWidget,
)
from django_smartbase_admin.mcp_log.models import MCPRequestLog
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView


def _round_value(sub_widget, request, value):
    return round(value or 0)


def _kb_value(sub_widget, request, value):
    return round((value or 0) / 1024)


class MCPRecentCallsListWidget(SBAdminDashboardListWidget):
    name = _("Calls")
    model = MCPRequestLog
    list_per_page = 20
    ordering = ["-timestamp"]
    sbadmin_list_history_enabled = False

    @staticmethod
    def _user_attr():
        """``email`` if the user model has it, else ``USERNAME_FIELD``."""
        user_model = get_user_model()
        names = {f.name for f in user_model._meta.get_fields()}
        return "email" if "email" in names else user_model.USERNAME_FIELD

    @classmethod
    def _user_label(cls, request, item):
        return getattr(item, cls._user_attr(), None) or str(item)

    @staticmethod
    def _duration_label(object_id, value):
        if value is None:
            return ""
        return format_badge(f"{value} ms", BadgeType.NEUTRAL)

    @staticmethod
    def _error_label(object_id, value):
        if value:
            return format_badge(_("Yes"), BadgeType.ERROR)
        return format_badge(_("No"), BadgeType.SUCCESS)

    def __init__(self, **kwargs):
        kwargs.setdefault("sbadmin_list_display", self._build_list_display())
        super().__init__(**kwargs)

    def _build_list_display(self):
        return [
            SBAdminField(
                name="timestamp", title=_("Time"), filter_widget=DateFilterWidget()
            ),
            SBAdminField(
                name="user_label",
                title=_("User"),
                annotate=Coalesce(
                    F(f"user__{self._user_attr()}"),
                    Value(""),
                    output_field=TextField(),
                ),
                filter_field="user",
                filter_widget=AutocompleteFilterWidget(
                    model=get_user_model(),
                    multiselect=True,
                    value_field="id",
                    label_lambda=self._user_label,
                ),
            ),
            SBAdminField(
                name="tool_name",
                title=_("Tool"),
                filter_field="tool_name",
                filter_widget=FromValuesAutocompleteWidget(multiselect=True),
            ),
            SBAdminField(name="result_total", title=_("Record count")),
            SBAdminField(
                name="duration_ms",
                title=_("Duration"),
                formatter="html",
                python_formatter=self._duration_label,
            ),
            SBAdminField(
                name="is_error",
                title=_("Error"),
                formatter="html",
                python_formatter=self._error_label,
                filter_field="is_error",
                filter_widget=BooleanFilterWidget(),
            ),
        ]

    def has_view_permission(self, request, obj=None) -> bool:
        return True


class MCPCallsChartWidget(SBAdminDashboardLineChartWidgetByDate):
    """Calls over time, with native date-range filter and a Total / By user
    grouping (one line vs one line per calling user)."""

    name = _("MCP calls")
    model = MCPRequestLog
    date_annotate_field = "timestamp"
    GROUP_KEY = "__mcp_group__"

    # Cards over the chart: each is an aggregate AND the active series for the
    # line. They share the chart's date-range filter, so the numbers track the
    # selected period (no separate retention-window widget).
    sub_widgets = [
        SBAdminChartAggregateSubWidget(title=_("Calls"), aggregate=Count("id")),
        SBAdminChartAggregateSubWidget(
            title=_("Errors"), aggregate=Count("id", filter=Q(is_error=True))
        ),
        SBAdminChartAggregateSubWidget(
            title=_("Avg duration (ms)"),
            aggregate=Avg("duration_ms"),
            python_formatter=_round_value,
        ),
        SBAdminChartAggregateSubWidget(
            title=_("Items returned"), aggregate=Sum("result_total")
        ),
        SBAdminChartAggregateSubWidget(
            title=_("Request (KB)"),
            aggregate=Sum("request_size"),
            python_formatter=_kb_value,
        ),
        SBAdminChartAggregateSubWidget(
            title=_("Response (KB)"),
            aggregate=Sum("response_size"),
            python_formatter=_kb_value,
        ),
    ]

    class GroupOptions(models.TextChoices):
        TOTAL = "total", _("Total")
        USER = "user", _("By user")

    def __init__(self, **kwargs):
        kwargs.setdefault("y_axis_annotate", Count("id"))
        kwargs["settings"] = [
            SBAdminField(
                name=self.GROUP_KEY,
                title=_("Grouping"),
                filter_widget=RadioChoiceFilterWidget(
                    choices=self.GroupOptions.choices,
                    default_value=self.GroupOptions.TOTAL,
                    allow_clear=False,
                ),
            ),
            *(kwargs.get("settings") or []),
        ]
        super().__init__(**kwargs)
        self._prune_settings()

    def _prune_settings(self):
        """Drop the whole period-compare picker (pointless here) and the "Year"
        resolution option. The enum members stay so the chart's annotate/compare
        logic keeps working; with no compare field, ``get_data`` reads it as
        ``None`` and skips comparison entirely."""
        year = self.DateResolutionsOptions.DATE_RESOLUTION_YEAR.value
        self.settings = [
            field for field in self.get_settings() if field.name != self.COMPARE_KEY
        ]
        for field in self.get_settings():
            if field.name == self.RESOLUTION_KEY:
                widget = field.filter_widget
                widget.choices = [c for c in widget.choices if c[0] != year]

    def get_date_widget_shortcuts(self):
        # Drop "Last Year"; keep Last 30 days and Last Quarter (default).
        return [
            shortcut
            for shortcut in super().get_date_widget_shortcuts()
            if shortcut["value"] != [-365, 0]
        ]

    def has_view_permission(self, request, obj=None) -> bool:
        return True

    def _group_by_user(self, request):
        value = self.get_settings_from_request(request).get(self.GROUP_KEY)
        return value == self.GroupOptions.USER

    def get_data(self, request):
        # Total mode: the stock single-line behaviour (incl. compare).
        if not self._group_by_user(request):
            return super().get_data(request)

        # By-user mode: one dataset (line) per calling user, using whichever
        # metric (card) is currently active for the y-axis.
        user_field = f"user__{MCPRecentCallsListWidget._user_attr()}"
        rows = list(
            self.get_data_queryset(request)
            .annotate(x_axis=self.get_x_axis_annotate(request))
            .values("x_axis", user_field)
            .annotate(y_axis=self.get_y_axis_annotate(request))
            .order_by("x_axis")
        )
        buckets, seen = [], set()
        for row in rows:
            if row["x_axis"] not in seen:
                seen.add(row["x_axis"])
                buckets.append(row["x_axis"])
        index = {bucket: i for i, bucket in enumerate(buckets)}
        series: dict = {}
        for row in rows:
            label = row.get(user_field) or "—"
            series.setdefault(label, [0] * len(buckets))[index[row["x_axis"]]] += row[
                "y_axis"
            ]
        labels = [
            self.process_label(request, bucket, None, [], []) for bucket in buckets
        ]
        datasets = [
            {"label": label, "data": data, "fill": False}
            for label, data in series.items()
        ]
        return {"main": {"labels": labels, "datasets": datasets}, "sub_widget": {}}


class MCPLogDashboardView(SBAdminDashboardView):
    view_id = "aiassistantmodule"
    label = _("AI Assistant Module")
    menu_action = "aiassistantmodule"

    def __init__(self, title=None, widgets=None):
        widgets = widgets or [
            MCPCallsChartWidget(),
            MCPRecentCallsListWidget(),
        ]
        super().__init__(title=title or str(self.label), widgets=widgets)

    def has_view_permission(self, request, obj=None) -> bool:
        return True

    @sbadmin_action
    def aiassistantmodule(self, request, modifier, object_id=None):
        context = self.get_global_context(request)
        widget_views = self.get_widget_views(request, object_id)
        context["direct_sub_views"] = widget_views
        context["dashboard_media"] = self.get_dashboard_media(request, widget_views)
        context["title"] = self.get_title()
        return TemplateResponse(
            request, "sb_admin/actions/dashboard.html", context=context
        )
