"""SBAdmin registration for the MCP log models — read-only browsing."""

import json
import re

from django.contrib.auth import get_user_model
from django.db.models import F, TextField, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import BadgeType, format_badge
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    BooleanFilterWidget,
    FromValuesAutocompleteWidget,
)
from django_smartbase_admin.mcp_log.models import MCPRequestLog
from django_smartbase_admin.services.views import SBAdminViewService

# The AI Assistant Module dashboard (see dashboard.MCPLogDashboardView).
DASHBOARD_VIEW_ID = "aiassistantmodule"


class MCPRequestLogAdmin(SBAdmin):
    """Read-only view of individual MCP tool calls."""

    sbadmin_list_history_enabled = False

    # ``email`` if the user model has it, else its ``USERNAME_FIELD`` — so this
    # works for any AUTH_USER_MODEL without raising a FieldError.
    _user_field = (
        "email"
        if "email" in {f.name for f in get_user_model()._meta.get_fields()}
        else get_user_model().USERNAME_FIELD
    )

    _json_token_re = re.compile(
        r'("(?:\\u[0-9a-fA-F]{4}|\\.|[^"\\])*"\s*:)'  # key
        r'|("(?:\\u[0-9a-fA-F]{4}|\\.|[^"\\])*")'  # string value
        r"|\b(true|false|null)\b"  # literal
        r"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"  # number
    )
    _json_colors = {
        "key": "#7c3aed",
        "str": "#0f766e",
        "lit": "#c2410c",
        "num": "#2563eb",
    }

    @classmethod
    def _highlight_json(cls, value):
        """Pretty-print + lightly syntax-highlight a JSON-able value as safe HTML.

        Only string/key tokens can carry HTML-special chars and those are escaped;
        structural characters between tokens are HTML-safe and pass through.
        """
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
        colors = cls._json_colors

        def repl(match):
            key, string, literal, number = match.groups()
            if key is not None:
                name = key.rpartition(":")[0]
                return (
                    f'<span style="color:{colors["key"]}">{escape(name.rstrip())}</span>'
                    f'<span style="color:#94a3b8">:</span>'
                )
            if string is not None:
                return f'<span style="color:{colors["str"]}">{escape(string)}</span>'
            if literal is not None:
                return f'<span style="color:{colors["lit"]}">{literal}</span>'
            return f'<span style="color:{colors["num"]}">{number}</span>'

        highlighted = cls._json_token_re.sub(repl, text)
        return mark_safe(
            '<pre style="margin:0;padding:14px 16px;background:#f8fafc;'
            "border:1px solid #e2e8f0;border-radius:8px;max-height:480px;overflow:auto;"
            'font-size:12.5px;line-height:1.6;white-space:pre;color:#0f172a;">'
            f"{highlighted}</pre>"
        )

    sbadmin_list_display = (
        SBAdminField(name="timestamp", title=_("Time"), filter_disabled=True),
        SBAdminField(
            name="tool_name",
            title=_("Tool"),
            filter_field="tool_name",
            filter_widget=FromValuesAutocompleteWidget(multiselect=True),
        ),
        SBAdminField(
            name="user_display",
            title=_("User"),
            annotate=Coalesce(
                F(f"user__{_user_field}"), Value(""), output_field=TextField()
            ),
            filter_field="user",
            filter_widget=AutocompleteFilterWidget(
                model=get_user_model(),
                multiselect=True,
                value_field="id",
                label_lambda=lambda request, item: getattr(item, "email", None)
                or getattr(item, item.USERNAME_FIELD, None)
                or str(item),
            ),
        ),
        SBAdminField(
            name="outcome_display",
            title=_("Outcome"),
            annotate=F("is_error"),
            supporting_annotates={"error_type_val": F("error_type")},
            formatter="html",
            filter_field="is_error",
            filter_widget=BooleanFilterWidget(),
        ),
        SBAdminField(
            name="result_total", title=_("Record count"), filter_disabled=True
        ),
        SBAdminField(
            name="duration_ms", title=_("Duration (ms)"), filter_disabled=True
        ),
        SBAdminField(name="request_size", title=_("Request (B)"), filter_disabled=True),
        SBAdminField(
            name="response_size", title=_("Response (B)"), filter_disabled=True
        ),
    )

    sbadmin_list_filter = (
        "tool_name",
        "user_display",
        "outcome_display",
    )

    search_fields = ["tool_name", "error_type", "error_message"]
    date_hierarchy = "timestamp"
    ordering = ["-timestamp"]

    readonly_fields = [
        "timestamp",
        "user",
        "tool_name",
        "duration_ms",
        "request_size",
        "response_size",
        "is_error",
        "error_type",
        "arguments_html",
        "error_message",
        "result_status",
        "result_total",
        "result_fields",
        "result_inlines",
        "result_inline_rows",
    ]

    sbadmin_fieldsets = [
        (
            _("Details"),
            {
                "fields": [
                    "timestamp",
                    "user",
                    "tool_name",
                    "is_error",
                    "error_type",
                    "duration_ms",
                    "request_size",
                    "response_size",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (_("Request"), {"fields": ["arguments_html", "error_message"]}),
        (
            _("Response"),
            {
                "fields": [
                    (
                        "result_status",
                        "result_total",
                    ),
                    (
                        "result_fields",
                        "result_inlines",
                    ),
                    "result_inline_rows",
                ],
            },
        ),
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_change_view_context(self, request, object_id):
        context = super().get_change_view_context(request, object_id)
        dashboard_url = reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": DASHBOARD_VIEW_ID,
                "action": DASHBOARD_VIEW_ID,
                "modifier": "template",
            },
        )
        context["back_url"] = SBAdminViewService.resolve_back_url(
            request, dashboard_url, current_path=request.path
        )
        return context

    def user_display(self, obj_id, value, **additional_data):
        return value if value else "-"

    def outcome_display(self, obj_id, value, **additional_data):
        if value:
            label = additional_data.get("error_type_val") or _("Error")
            return format_badge(label, BadgeType.ERROR)
        return format_badge(_("OK"), BadgeType.SUCCESS)

    def arguments_html(self, obj):
        if not obj or not obj.arguments:
            return "-"
        return self._highlight_json(obj.arguments)

    arguments_html.short_description = None
