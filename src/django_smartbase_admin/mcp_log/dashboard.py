"""Dashboard over ``MCPRequestLog`` — branded "AI Assistant Module".

Two widgets on a standard ``SBAdminDashboardView``:

* :class:`MCPLogStatsWidget` — server-rendered stat cards + per-tool bars
  (no AJAX, always renders).
* :class:`MCPRecentCallsListWidget` — a filterable/sortable Tabulator list of
  recent calls (incl. the calling user).

Registered via the project's ``SBAdminConfiguration.registered_views``;
reachable at ``/sb-admin/aiassistantmodule/aiassistantmodule/template/``.
"""

import json
from datetime import date, timedelta

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
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    BooleanFilterWidget,
    DateFilterWidget,
    FromValuesAutocompleteWidget,
)
from django_smartbase_admin.mcp_log.models import MCPRequestLog
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

DEFAULT_DAYS = 30
SESSION_RANGE_KEY = "mcp_log_range"
FILTER_FIELD = "timestamp"

# Shortcuts shown inside the native DateFilterWidget calendar dropdown.
DATE_SHORTCUTS = [
    (30, _("Last 30 days")),
    (90, _("Last Quarter")),
    (365, _("Last Year")),
]
DAYS_LABEL = dict(DATE_SHORTCUTS)
WIDGET_SHORTCUTS = [
    {"value": [-days, 0], "label": label} for days, label in DATE_SHORTCUTS
]
DEFAULT_SHORTCUT_INDEX = 0  # "Last 30 days"


def _kb(value):
    return round((value or 0) / 1024)


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _days_from_value(value):
    """Return N if ``value`` is a shortcut ``[-N, 0]`` blob, else None."""
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None
    if (
        isinstance(parsed, list)
        and len(parsed) == 2
        and parsed[1] == 0
        and isinstance(parsed[0], (int, float))
    ):
        return abs(int(parsed[0]))
    return None


def _store_range_from_request(request):
    """Persist the DateFilterWidget value (submitted as ``timestamp``) to the
    session, so every widget — including the list's Tabulator AJAX — reads the same
    window on subsequent requests (full page reload model)."""
    value = request.GET.get(FILTER_FIELD)
    if value is None:
        return
    date_from, date_to = DateFilterWidget.get_range_from_value(value)
    if not date_from and not date_to:
        request.session.pop(SESSION_RANGE_KEY, None)  # cleared → default
        return
    days = _days_from_value(value)
    if days in DAYS_LABEL:
        label = str(DAYS_LABEL[days])
    else:
        label = " – ".join(d.strftime("%d.%m.%Y") for d in (date_from, date_to) if d)
    request.session[SESSION_RANGE_KEY] = {
        # date-only strings so date.fromisoformat round-trips (get_range_from_value
        # returns datetimes with time/tz, which date.fromisoformat rejects).
        "from": date_from.strftime("%Y-%m-%d") if date_from else None,
        "to": date_to.strftime("%Y-%m-%d") if date_to else None,
        "label": label,
    }


def _current_range(request):
    raw = (getattr(request, "session", None) or {}).get(SESSION_RANGE_KEY)
    if not isinstance(raw, dict):
        raw = {}
    date_from = _parse_date(raw.get("from"))
    date_to = _parse_date(raw.get("to"))
    label = raw.get("label")
    if not date_from and not date_to:
        date_from = timezone.localdate() - timedelta(days=DEFAULT_DAYS)
        label = str(DAYS_LABEL.get(DEFAULT_DAYS))
    return date_from, date_to, label


def _filter_range(qs, request):
    date_from, date_to, _label = _current_range(request)
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)
    return qs


def _date_filter_field():
    return SBAdminField(
        name=FILTER_FIELD,
        title=_("Date"),
        filter_field=FILTER_FIELD,
        filter_widget=DateFilterWidget(
            shortcuts=WIDGET_SHORTCUTS,
            default_value_shortcut_index=DEFAULT_SHORTCUT_INDEX,
        ),
    )


class MCPLogStatsWidget(SBAdminDashboardWidget):
    template_name = "sb_admin/mcp_log/stats_widget.html"
    model = MCPRequestLog

    def __init__(self, **kwargs):
        kwargs.setdefault("filters", [_date_filter_field()])
        super().__init__(**kwargs)

    def has_view_permission(self, request, obj=None) -> bool:
        return True

    def get_widget_context_data(self, request):
        context = super().get_widget_context_data(request)
        qs = _filter_range(MCPRequestLog.objects.all(), request)

        totals = qs.aggregate(
            calls=Count("id"),
            errors=Count("id", filter=Q(is_error=True)),
            avg_duration=Avg("duration_ms"),
            items=Sum("result_count"),
            req_bytes=Sum("request_size"),
            resp_bytes=Sum("response_size"),
        )
        calls = totals["calls"] or 0
        errors = totals["errors"] or 0

        context.update(
            {
                "current_date_label": _current_range(request)[2],
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
                    {"label": _("Request (KB)"), "value": _kb(totals["req_bytes"])},
                    {"label": _("Response (KB)"), "value": _kb(totals["resp_bytes"])},
                ],
            }
        )
        return context


class MCPRecentCallsListWidget(SBAdminDashboardListWidget):
    template_name = "sb_admin/mcp_log/recent_calls_widget.html"
    name = _("Recent calls")
    model = MCPRequestLog
    list_per_page = 20
    ordering = ["-timestamp"]
    sbadmin_list_history_enabled = False

    sbadmin_list_display = [
        SBAdminField(
            name="timestamp", title=_("Time"), filter_widget=DateFilterWidget()
        ),
        SBAdminField(
            name="user_email",
            title=_("User"),
            annotate=Coalesce(F("user__email"), Value(""), output_field=TextField()),
            filter_field="user",
            filter_widget=AutocompleteFilterWidget(
                model=get_user_model(),
                multiselect=True,
                value_field="id",
                label_lambda=lambda request, item: item.email or str(item),
            ),
        ),
        SBAdminField(
            name="tool_name",
            title=_("Tool"),
            filter_field="tool_name",
            filter_widget=FromValuesAutocompleteWidget(multiselect=True),
        ),
        SBAdminField(name="result_count", title=_("Items")),
        SBAdminField(name="duration_ms", title=_("Duration (ms)")),
        SBAdminField(
            name="is_error",
            title=_("Error"),
            filter_field="is_error",
            filter_widget=BooleanFilterWidget(),
        ),
    ]

    def has_view_permission(self, request, obj=None) -> bool:
        return True

    def get_queryset(self, request=None):
        return _filter_range(super().get_queryset(request), request)


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
        _store_range_from_request(request)
        context = self.get_global_context(request)
        widget_views = self.get_widget_views(request, object_id)
        context["direct_sub_views"] = widget_views
        context["dashboard_media"] = self.get_dashboard_media(request, widget_views)
        context["title"] = self.get_title()
        return TemplateResponse(
            request, "sb_admin/actions/dashboard.html", context=context
        )
