"""
SBAdmin registration for AdminAuditLog.
Provides rich filtering and history browsing.
"""

import json
from pprint import pformat

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q, TextField, Value
from django.db.models.functions import Coalesce, Concat
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    AutocompleteParseMixin,
    BooleanFilterWidget,
    MultipleChoiceFilterWidget,
    SBAdminFilterWidget,
)

from django_smartbase_admin.audit.models import AdminAuditLog


def _content_type_filter(request, search_term, forward_data):
    """Pre-filter to only content types that have audit logs."""
    ct_ids = AdminAuditLog.objects.values_list("content_type", flat=True).distinct()
    return Q(pk__in=ct_ids)


def _user_filter(request, search_term, forward_data):
    """Pre-filter to only users that have audit logs."""
    user_ids = AdminAuditLog.objects.values_list("user", flat=True).distinct()
    return Q(pk__in=user_ids)


class ObjectHistoryFilterWidget(AutocompleteParseMixin, SBAdminFilterWidget):
    """
    Filter for viewing all changes related to a specific object.

    Uses the MultipleChoice template to display nicely with value/label format.
    Applies OR filtering across:
    - Direct changes (content_type + object_id)
    - Parent context (parent_content_type + parent_object_id)
    - Affected objects (affected_objects JSON contains)

    Value format: [{"value": "10:3", "label": "user_config.queuebundle #3"}]
    The value encodes content_type_id:object_id
    """

    template_name = "sb_admin/filter_widgets/multiple_choice_field.html"
    close_dropdown_on_change = False

    def __init__(self):
        super().__init__(
            filter_query_lambda=self._filter_by_object_history,
        )
        # Empty choices - values come from URL
        self.choices = []
        self.enable_select_all = False

    @staticmethod
    def parse_filter_value(value):
        """
        Parse a single filter value into content_type_id and object_id.

        Args:
            value: String in format "content_type_id:object_id"

        Returns:
            Tuple of (content_type_id, object_id) or (None, None) if invalid.
        """
        try:
            parts = str(value).split(":")
            if len(parts) != 2:
                return None, None
            content_type_id = int(parts[0])
            object_id = parts[1]
            return content_type_id, object_id
        except (ValueError, TypeError, AttributeError):
            return None, None

    def _filter_by_object_history(self, request, parsed_values):
        """Build OR query for object history."""
        if not parsed_values:
            return Q()

        q = Q()
        for value in parsed_values:
            content_type_id, object_id = self.parse_filter_value(value)
            if content_type_id is None:
                continue

            # Get content type label for JSON query
            try:
                ct = ContentType.objects.get(pk=content_type_id)
                ct_label = f"{ct.app_label}.{ct.model}"
            except ContentType.DoesNotExist:
                continue

            # Try to convert object_id to int for JSON lookup
            try:
                obj_pk = int(object_id)
            except (ValueError, TypeError):
                obj_pk = object_id

            # OR filter: direct changes, parent context, or affected (JSON contains)
            q |= (
                Q(content_type_id=content_type_id, object_id=str(object_id))
                | Q(
                    parent_content_type_id=content_type_id,
                    parent_object_id=str(object_id),
                )
                | Q(affected_objects__contains=[{"ct": ct_label, "id": obj_pk}])
            )

        return q if q else Q()


ACTION_COLORS = {
    "create": "success",
    "update": "notice",
    "delete": "negative",
    "bulk_create": "success",
    "bulk_update": "notice",
    "bulk_delete": "negative",
}

ACTION_ICONS = {
    "create": "Check-one",
    "update": "Edit",
    "delete": "Close-one",
    "bulk_create": "Check-one",
    "bulk_update": "Edit",
    "bulk_delete": "Close-one",
}


class AdminAuditLogAdmin(SBAdmin):
    """SBAdmin for viewing audit logs."""

    sbadmin_list_display = (
        SBAdminField(name="timestamp", title="Time", filter_disabled=True),
        SBAdminField(
            name="summary_display",
            title="Summary",
            annotate=F("object_repr"),  # Main value, method builds full summary
            formatter="html",
            supporting_annotates={
                "summary_action": F("action_type"),
                "summary_model": F("content_type__model"),
                "summary_is_bulk": F("is_bulk"),
                "summary_bulk_count": F("bulk_count"),
                "summary_parent_model": F("parent_content_type__model"),
                "summary_parent_repr": F("parent_object_repr"),
                "summary_parent_ct_id": F("parent_content_type_id"),
                "summary_parent_obj_id": F("parent_object_id"),
                "summary_ct_id": F("content_type_id"),
                "summary_obj_id": F("object_id"),
                "summary_changes": F("changes"),
            },
            filter_disabled=True,
        ),
        SBAdminField(
            name="user_display",
            title="User",
            annotate=Coalesce(F("user__email"), Value(""), output_field=TextField()),
            filter_field="user",
            filter_widget=AutocompleteFilterWidget(
                model=get_user_model(),
                multiselect=True,
                value_field="id",
                label_lambda=lambda request, item: item.email or str(item),
                filter_search_lambda=_user_filter,
            ),
        ),
        SBAdminField(
            name="action_type_display",
            title="Action",
            annotate=F("action_type"),
            filter_field="action_type",
            filter_widget=MultipleChoiceFilterWidget(
                choices=AdminAuditLog.ActionType.choices, multiselect=True
            ),
        ),
        SBAdminField(
            name="model_display",
            title="Model",
            annotate=Concat(
                F("content_type__app_label"),
                Value("."),
                F("content_type__model"),
                output_field=TextField(),
            ),
            filter_field="content_type",
            filter_widget=AutocompleteFilterWidget(
                model=ContentType,
                multiselect=True,
                value_field="id",
                label_lambda=lambda request, item: f"{item.app_label}.{item.model}",
                filter_search_lambda=_content_type_filter,
            ),
        ),
        SBAdminField(
            name="bulk_info",
            title="Bulk",
            annotate=F("is_bulk"),
            supporting_annotates={"bulk_count_val": F("bulk_count")},
            filter_field="is_bulk",
            filter_widget=BooleanFilterWidget(),
        ),
        # Filter for object history (used by history redirect)
        SBAdminField(
            name="object_history_filter",
            title="Object History",
            annotate=Value("", output_field=TextField()),
            filter_field="object_history",
            filter_widget=ObjectHistoryFilterWidget(),
            list_visible=False,
        ),
    )

    # SBAdmin filters - use field names from sbadmin_list_display
    sbadmin_list_filter = (
        "object_history_filter",
        "action_type_display",
        "model_display",
        "user_display",
        "bulk_info",
    )

    search_fields = ["object_repr", "object_id", "parent_object_repr"]
    date_hierarchy = "timestamp"
    ordering = ["-timestamp"]
    readonly_fields = [
        "timestamp",
        "user",
        "content_type",
        "object_id",
        "object_repr",
        "parent_content_type",
        "parent_object_id",
        "parent_object_repr",
        "action_type",
        "is_bulk",
        "bulk_count",
        "summary_html",
        "changes_html",
        "affected_html",
        "related_changes_html",
    ]

    sbadmin_fieldsets = [
        # Main content
        (
            None,
            {
                "fields": [
                    "summary_html",
                    "changes_html",
                    "affected_html",
                    "related_changes_html",
                ],
            },
        ),
        # Sidebar - key metadata
        (
            _("Details"),
            {
                "fields": [
                    "timestamp",
                    "user",
                    "action_type",
                    "content_type",
                    "object_id",
                    "object_repr",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            _("Bulk"),
            {
                "fields": [
                    "is_bulk",
                    "bulk_count",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS, "collapse"],
            },
        ),
        (
            _("Parent Context"),
            {
                "fields": [
                    "parent_content_type",
                    "parent_object_id",
                    "parent_object_repr",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS, "collapse"],
            },
        ),
    ]

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        if request and hasattr(request, "user") and not request.user.is_superuser:
            # Non-superusers only see their own entries in the global view.
            # When object_history filter is active (viewing a specific object's history),
            # show all entries — the user already had access to that object.
            if not self._parse_and_cache_object_history_filter(request):
                qs = qs.filter(user=request.user)
        return qs

    def _parse_and_cache_object_history_filter(self, request):
        """Parse object_history filter from request, cache the result, return it.

        Returns tuple (content_type_id, object_id) or None.
        Subsequent calls (including from action_list_json via _get_object_history_filter)
        will read from the cache without re-parsing.
        """
        # Return cached value if already parsed
        if hasattr(request, "request_data"):
            cached = request.request_data.additional_data.get(
                self._OBJECT_HISTORY_FILTER_CACHE_KEY
            )
            if cached is not None:
                return cached

        result = None
        try:
            action = self.sbadmin_list_action_class(self, request)
            raw_value = action.filter_data.get("object_history")
            if raw_value:
                filter_widget = self._get_object_history_widget()
                if filter_widget:
                    parsed_values = filter_widget.parse_value_from_input(
                        request, raw_value
                    )
                    if parsed_values and len(parsed_values) > 0:
                        ct_id, obj_id = ObjectHistoryFilterWidget.parse_filter_value(
                            parsed_values[0]
                        )
                        if ct_id is not None:
                            result = (ct_id, obj_id)
        except Exception:
            pass

        # Cache on request so action_list_json and summary_display can reuse
        if hasattr(request, "request_data"):
            request.request_data.additional_data[
                self._OBJECT_HISTORY_FILTER_CACHE_KEY
            ] = result
        return result

    def get_change_view_context(self, request, object_id):
        ctx = super().get_change_view_context(request, object_id)
        ctx["show_history_button"] = False
        return ctx

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @staticmethod
    def _change_to_row(field_name, change):
        """Classify a single change dict into a template row."""
        if "old" in change or "new" in change:
            return {
                "field_name": field_name,
                "type": "changed",
                "old_val": change.get("old_display")
                or change.get("old")
                or _("(empty)"),
                "new_val": change.get("new_display")
                or change.get("new")
                or _("(empty)"),
            }
        if "by_old" in change:
            return {
                "field_name": field_name,
                "type": "bulk",
                "new_val": change.get("new"),
                "groups": [
                    {"old_val": old_val, "count": len(ids)}
                    for old_val, ids in change["by_old"].items()
                ],
            }
        return {
            "field_name": field_name,
            "type": "raw",
            "raw": pformat(change),
        }

    def changes_html(self, obj):
        """Render unified changes view: snapshot fields with changed ones showing old->new."""
        if not obj:
            return "-"

        changes = obj.changes or {}
        snapshot = obj.snapshot_before or {}

        rows = []

        # Build rows from snapshot (preserves field order), marking changed ones
        for field_name, value in snapshot.items():
            change = changes.get(field_name)
            if change:
                rows.append(self._change_to_row(field_name, change))
            else:
                str_val = str(value) if value is not None else ""
                rows.append(
                    {
                        "field_name": field_name,
                        "type": "unchanged",
                        "value": str_val if str_val != "" else _("(empty)"),
                        "is_long": len(str_val) > 80 or "\n" in str_val,
                    }
                )

        # Add any changes not in snapshot (e.g. new fields on create)
        for field_name, change in changes.items():
            if field_name not in snapshot:
                rows.append(self._change_to_row(field_name, change))

        if not rows and not obj.is_bulk:
            return "-"

        return mark_safe(
            render_to_string(
                "sb_admin/audit/changes.html",
                {
                    "is_bulk": obj.is_bulk,
                    "bulk_count": obj.bulk_count,
                    "rows": rows,
                },
            )
        )

    changes_html.short_description = _("Changes")

    def affected_html(self, obj):
        """Render affected objects as formatted HTML for detail view."""
        if not obj or not obj.affected_objects:
            return mark_safe(
                render_to_string(
                    "sb_admin/audit/affected.html",
                )
            )

        # Group by content type
        by_type = {}
        for item in obj.affected_objects:
            ct = item.get("ct", "unknown")
            model_name = (
                ct.split(".")[-1].replace("_", " ").title() if "." in ct else ct
            )
            by_type.setdefault(model_name, []).append(item)

        sections = []
        for model_name, items in by_type.items():
            badges = []
            for item in items[:25]:
                repr_str = item.get("repr", "")
                obj_id = item.get("id", "?")
                if repr_str and str(repr_str) != str(obj_id):
                    badges.append(f"{repr_str} (#{obj_id})")
                else:
                    badges.append(f"#{obj_id}")
            sections.append(
                {
                    "model_name": model_name,
                    "badges": badges,
                    "extra_count": len(items) - 25 if len(items) > 25 else 0,
                }
            )

        return mark_safe(
            render_to_string(
                "sb_admin/audit/affected.html",
                {
                    "sections": sections,
                },
            )
        )

    affected_html.short_description = _("Affected Objects")

    def related_changes_html(self, obj):
        """Render other changes made in the same request."""
        if not obj or not obj.request_id:
            return ""

        qs = (
            AdminAuditLog.objects.filter(request_id=obj.request_id)
            .exclude(pk=obj.pk)
            .select_related("content_type")
            .order_by("timestamp")
        )
        total = qs.count()
        if not total:
            return ""

        from django_smartbase_admin.audit.views import _get_audit_view_id

        action_labels = dict(AdminAuditLog.ActionType.choices)
        rows = []
        for log in qs[:20]:
            url = None
            try:
                url = reverse(f"sb_admin:{_get_audit_view_id()}_change", args=[log.pk])
            except Exception:
                pass
            rows.append(
                {
                    "color": ACTION_COLORS.get(log.action_type, "secondary"),
                    "label": action_labels.get(log.action_type, log.action_type),
                    "model_name": (
                        f"{log.content_type.app_label}.{log.content_type.model}"
                        if log.content_type
                        else "-"
                    ),
                    "url": url,
                    "obj_repr": log.object_repr or log.object_id or "-",
                }
            )

        return mark_safe(
            render_to_string(
                "sb_admin/audit/related_changes.html",
                {
                    "total": total,
                    "rows": rows,
                    "extra_count": total - 20 if total > 20 else 0,
                },
            )
        )

    related_changes_html.short_description = _("Related Changes")

    _OBJECT_HISTORY_FILTER_CACHE_KEY = "_audit_object_history_filter"

    def action_list_json(self, request, modifier, page_size=None):
        """Override to ensure object_history filter is cached before processing rows."""
        from django.http import JsonResponse

        # Ensure filter is parsed and cached (may already be done by get_queryset)
        self._parse_and_cache_object_history_filter(request)
        action = self.sbadmin_list_action_class(self, request, page_size=page_size)
        data = action.get_json_data()
        return JsonResponse(data=data, safe=False)

    def _get_object_history_widget(self):
        """Get the ObjectHistoryFilterWidget instance from sbadmin_list_display."""
        for field in self.sbadmin_list_display:
            if field.filter_field == "object_history" and isinstance(
                field.filter_widget, ObjectHistoryFilterWidget
            ):
                return field.filter_widget
        return None

    def _get_object_history_filter(self):
        """Get cached object_history filter value.

        Returns tuple (content_type_id, object_id) or None if not filtered.
        Cached by _parse_and_cache_object_history_filter (called from get_queryset / action_list_json).
        """
        try:
            from django_smartbase_admin.services.thread_local import (
                SBAdminThreadLocalService,
            )

            request = SBAdminThreadLocalService.get_request()
            if request and hasattr(request, "request_data"):
                return request.request_data.additional_data.get(
                    self._OBJECT_HISTORY_FILTER_CACHE_KEY
                )
        except Exception:
            pass
        return None

    @staticmethod
    def _filter_matches(filter_obj, ct_id, obj_id):
        """Check if a (content_type_id, object_id) pair matches the active filter."""
        if not filter_obj or not ct_id:
            return False
        return str(ct_id) == str(filter_obj[0]) and str(obj_id) == str(filter_obj[1])

    @staticmethod
    def _build_summary(
        action,
        model,
        obj_repr,
        is_bulk,
        bulk_count,
        changes,
        parent_model="",
        parent_repr="",
        hide_obj=False,
        hide_parent=False,
    ):
        """Build summary message and parent context string.

        Returns:
            Tuple of (message, parent_context) where parent_context may be empty.
        """
        subject = "" if hide_obj else f'{model} "{obj_repr}" '

        if is_bulk:
            msg = f'{action.replace("_", " ").title()} {bulk_count} {model}{"s" if bulk_count != 1 else ""}.'
        elif action == "create":
            msg = f"Added {subject.strip()}."
        elif action == "delete":
            msg = f"Deleted {subject.strip()}."
        else:
            changed_fields = list(changes.keys()) if isinstance(changes, dict) else []
            if changed_fields:
                fields_str = ", ".join(f.replace("_", " ") for f in changed_fields[:5])
                if len(changed_fields) > 5:
                    fields_str += f" (+{len(changed_fields) - 5} more)"
                msg = f"Changed {subject}— {fields_str}."
            else:
                msg = f"Changed {subject.strip()}."

        parent_context = ""
        if parent_model and parent_repr and not hide_parent:
            parent_context = f'in {parent_model.replace("_", " ")} "{parent_repr}"'

        return msg, parent_context

    def summary_display(self, obj_id, value, **additional_data):
        """Build summary from annotated fields for list view."""
        filter_obj = self._get_object_history_filter()

        msg, parent_context = self._build_summary(
            action=additional_data.get("summary_action", ""),
            model=(additional_data.get("summary_model") or "").replace("_", " "),
            obj_repr=escape(value or ""),
            is_bulk=additional_data.get("summary_is_bulk", False),
            bulk_count=additional_data.get("summary_bulk_count", 0),
            changes=additional_data.get("summary_changes") or {},
            parent_model=additional_data.get("summary_parent_model") or "",
            parent_repr=escape(additional_data.get("summary_parent_repr") or ""),
            hide_obj=self._filter_matches(
                filter_obj,
                additional_data.get("summary_ct_id"),
                additional_data.get("summary_obj_id"),
            ),
            hide_parent=self._filter_matches(
                filter_obj,
                additional_data.get("summary_parent_ct_id"),
                additional_data.get("summary_parent_obj_id"),
            ),
        )

        lines = [f"<div>{msg}</div>"]
        if parent_context:
            lines.append(f'<div class="text-muted small">↳ {parent_context}</div>')

        return mark_safe(f'<div style="display:block">{"".join(lines)}</div>')

    def summary_html(self, obj):
        """Render summary as styled HTML for detail view."""
        if not obj:
            return "-"

        msg, parent_context = self._build_summary(
            action=obj.action_type,
            model=(
                obj.content_type.model.replace("_", " ")
                if obj.content_type
                else "object"
            ),
            obj_repr=obj.object_repr or f"#{obj.object_id}",
            is_bulk=obj.is_bulk,
            bulk_count=obj.bulk_count or 0,
            changes=obj.changes,
            parent_model=(
                obj.parent_content_type.model if obj.parent_content_type else ""
            ),
            parent_repr=obj.parent_object_repr or "",
        )

        return mark_safe(
            render_to_string(
                "sb_admin/audit/summary.html",
                {
                    "message": msg,
                    "color": ACTION_COLORS.get(obj.action_type, "secondary"),
                    "icon": ACTION_ICONS.get(obj.action_type, ""),
                    "parent_context": parent_context,
                },
            )
        )

    summary_html.short_description = _("Summary")

    def user_display(self, obj_id, value, **additional_data):
        """Display the username or indicate if no user."""
        return value if value else "-"

    def action_type_display(self, obj_id, value, **additional_data):
        color = ACTION_COLORS.get(value, "secondary")
        label = dict(AdminAuditLog.ActionType.choices).get(value, value)
        return mark_safe(
            f'<span class="badge badge-simple badge-{color}">{label}</span>'
        )

    def bulk_info(self, obj_id, value, **additional_data):
        if value:
            count = additional_data.get("bulk_count_val", 0)
            return mark_safe(
                f'<span class="badge badge-simple badge-warning">{count} items</span>'
            )
        return "-"
