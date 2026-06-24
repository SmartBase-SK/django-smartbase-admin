"""Dashboard over ``MCPRequestLog`` — branded "AI Assistant Module".

Server-rendered stat cards for the retention window plus a filterable
recent-calls list. Registered via the project's
``SBAdminConfiguration.registered_views``; reachable at
``/sb-admin/aiassistantmodule/aiassistantmodule/template/``.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum, TextField, Value
from django.db.models.functions import Coalesce
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.dashboard import (
    SBAdminDashboardListWidget,
    SBAdminDashboardWidget,
)
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import BadgeType, format_badge
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    BooleanFilterWidget,
    DateFilterWidget,
    FromValuesAutocompleteWidget,
)
from django_smartbase_admin.mcp_log.models import MCPRequestLog
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

DEFAULT_PERIOD_DAYS = 60


class MCPLogStatsWidget(SBAdminDashboardWidget):
    """Stat cards aggregated over the retention window (no AJAX, always renders)."""

    template_name = "sb_admin/mcp_log/stats_widget.html"

    def has_view_permission(self, request, obj=None) -> bool:
        return True

    @staticmethod
    def _kb(value):
        return round((value or 0) / 1024)

    def get_period_days(self):
        return getattr(
            settings, "SB_ADMIN_MCP_REQUEST_LOG_RETENTION_DAYS", DEFAULT_PERIOD_DAYS
        )

    def get_widget_context_data(self, request):
        context = super().get_widget_context_data(request)
        days = self.get_period_days()
        since = timezone.now() - timedelta(days=days)
        qs = MCPRequestLog.objects.filter(timestamp__gte=since)

        totals = qs.aggregate(
            calls=Count("id"),
            errors=Count("id", filter=Q(is_error=True)),
            avg_duration=Avg("duration_ms"),
            items=Sum("result_total"),
            req_bytes=Sum("request_size"),
            resp_bytes=Sum("response_size"),
        )
        calls = totals["calls"] or 0
        errors = totals["errors"] or 0

        context.update(
            {
                "period_days": days,
                "stat_cards": [
                    {"label": _("Calls"), "value": calls},
                    {
                        "label": _("Errors"),
                        "value": errors,
                        "sub": f"{round(100 * errors / calls)}%" if calls else "0%",
                        "negative": errors > 0,
                    },
                    {
                        "label": _("Avg duration (ms)"),
                        "value": round(totals["avg_duration"] or 0),
                    },
                    {"label": _("Items returned"), "value": totals["items"] or 0},
                    {
                        "label": _("Request (KB)"),
                        "value": self._kb(totals["req_bytes"]),
                    },
                    {
                        "label": _("Response (KB)"),
                        "value": self._kb(totals["resp_bytes"]),
                    },
                ],
            }
        )
        return context


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


class MCPLogDashboardView(SBAdminDashboardView):
    view_id = "aiassistantmodule"
    label = _("AI Assistant Module")
    menu_action = "aiassistantmodule"

    def __init__(self, title=None, widgets=None):
        widgets = widgets or [MCPLogStatsWidget(), MCPRecentCallsListWidget()]
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
