"""SBAdmin registrations for the messaging feature.

- :class:`MessageAdmin` — management UI for authoring messages, gated by Django
  model permissions. Builds a config-driven form (type + audience selection) and
  syncs recipients on save; shows per-recipient read status.
- :class:`MessageInboxAdmin` — per-user inbox over ``MessageRecipient``. Visible
  to any authenticated (staff) user, scoped to their own rows. Opening a message
  marks it read, and it hosts the notification poll + acknowledge endpoints.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, TextField, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.admin_base import (
    SBAdmin,
    SBAdminTableInline,
    SBAdminTableInlinePaginated,
)
from django_smartbase_admin.engine.actions import SBAdminCustomAction, sbadmin_action
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import datetime_formatter
from django_smartbase_admin.engine.filter_widgets import StringFilterWidget
from django_smartbase_admin.messaging.config import NotificationStyle
from django_smartbase_admin.messaging.forms import (
    MessageForm,
    audience_field_name,
    build_message_form_class,
)
from django_smartbase_admin.messaging.models import (
    Message,
    MessageAttachment,
    MessageRecipient,
)
from django_smartbase_admin.messaging.services import SBAdminMessagingService
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.utils import SBAdminNoHistoryDetailMixin


class _MessageTypeBadgeMixin:
    """Provides a ``type_badge`` list-column method rendering the type badge."""

    def type_badge(self, obj_id, value, **additional_data):
        try:
            request = SBAdminThreadLocalService.get_request()
        except LookupError:
            request = None
        messaging_config = (
            SBAdminMessagingService.get_messaging_config(request) if request else None
        )
        return SBAdminMessagingService.render_message_type_badge(
            value, messaging_config
        )


def _bold_title_formatter(object_id, value):
    """Render a list cell value in bold."""
    return format_html('<span class="font-semibold">{}</span>', value or "")


def _read_status_badge(object_id, value):
    """Render a read/unread badge from a ``read_at`` value (success / negative)."""
    if value:
        return format_html(
            '<span class="badge badge-simple badge-positive">{}</span>', _("Read")
        )
    return format_html(
        '<span class="badge badge-simple badge-negative">{}</span>', _("Unread")
    )


def _sender_filter_query(request, value):
    """Match the sender (message author) by full name, email, or username."""
    if not value:
        return Q()
    username_field = get_user_model().USERNAME_FIELD
    return (
        Q(message__created_by__first_name__icontains=value)
        | Q(message__created_by__last_name__icontains=value)
        | Q(message__created_by__email__icontains=value)
        | Q(**{f"message__created_by__{username_field}__icontains": value})
    )


def new_message_action(send_view, request):
    """The shared "New message" toolbar action linking to the Message add view."""
    return SBAdminCustomAction(
        title=_("New message"),
        url=send_view.get_new_url(request),
        icon="Plus",
        css_class="btn btn-secondary",
    )


def render_message_card(message):
    """Render the read-only message detail card (header, content, attachments)."""
    from django.utils.safestring import mark_safe

    if not message:
        return "-"
    return mark_safe(
        render_to_string("sb_admin/messaging/detail_card.html", {"message": message})
    )


class MessageAttachmentInline(SBAdminTableInline):
    model = MessageAttachment
    fields = ["file"]
    extra = 1


class MessageRecipientStatusInline(SBAdminTableInlinePaginated):
    """Read-only listing of recipients + their read status ("who hasn't read")."""

    model = MessageRecipient
    fields = ["user", "notified_at", "read_at"]
    readonly_fields = ["user", "notified_at", "read_at"]
    extra = 0
    can_delete = False
    per_page = 10

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MessageAdmin(_MessageTypeBadgeMixin, SBAdminNoHistoryDetailMixin, SBAdmin):
    """Management UI for authoring/editing messages (Django model perms)."""

    form = MessageForm
    sbadmin_list_history_enabled = False

    sbadmin_list_display = (
        SBAdminField(
            name="title", title=_("Title"), python_formatter=_bold_title_formatter
        ),
        SBAdminField(
            name="type_badge",
            title=_("Type"),
            annotate=F("type"),
            filter_disabled=True,
        ),
        SBAdminField(name="created_at", title=_("Created")),
        SBAdminField(
            name="unread_count",
            title=_("Unread"),
            annotate=Count("recipients", filter=Q(recipients__read_at__isnull=True)),
            filter_disabled=True,
        ),
    )
    ordering = ["-created_at"]
    search_fields = ["title", "content"]

    inlines = [MessageAttachmentInline, MessageRecipientStatusInline]

    def get_queryset(self, request=None):
        # "Sent" view: scope to messages authored by the current user.
        qs = super().get_queryset(request)
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            return qs.filter(created_by=user)
        return qs

    def get_sbadmin_list_actions(self, request):
        # Use the same "New message" toolbar action as the inbox instead of the
        # framework's default "Add" button (suppressed in action_list below).
        actions = list(super().get_sbadmin_list_actions(request) or [])
        if self.has_add_permission(request):
            actions.append(new_message_action(self, request))
        return actions

    @sbadmin_action(permission="view")
    def action_list(self, request, *args, **kwargs):
        response = super().action_list(request, *args, **kwargs)
        # Hide the default "Add" button — the custom "New message" action above
        # replaces it so it matches the inbox button.
        content_context = getattr(response, "context_data", {}).get("content_context")
        if isinstance(content_context, dict):
            content_context["new_url"] = None
        return response

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        # Title the add form "New message" instead of "Add ...".
        if add:
            context["add_title"] = _("New message")
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def get_sbadmin_fieldsets(self, request, object_id=None):
        # Created message → single read-only detail card. Otherwise the editable
        # authoring form (content fields + recipient selectors on the right).
        if object_id is not None:
            return [(None, {"fields": ["message_card"]})]
        fieldsets = [(None, {"fields": ["title", "type", "content"]})]
        messaging_config = SBAdminMessagingService.get_messaging_config(request)
        audience_fields = []
        if messaging_config:
            for audience in messaging_config.audiences:
                if audience.get_form_field(request) is not None:
                    audience_fields.append(audience_field_name(audience.key))
        if audience_fields:
            fieldsets.append(
                (
                    _("Recipients"),
                    {
                        "fields": audience_fields,
                        "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
                    },
                )
            )
        return fieldsets

    def get_readonly_fields(self, request, obj=None):
        # A created message is immutable — render it as the read-only card.
        if obj is not None:
            return ("message_card",)
        return super().get_readonly_fields(request, obj)

    def get_inlines(self, request, obj=None):
        # Add: attachments editable. Existing message: only the (read-only)
        # recipient status inline — attachments are shown inside the card.
        if obj is None:
            return [MessageAttachmentInline]
        return [MessageRecipientStatusInline]

    def message_card(self, obj):
        return render_message_card(obj)

    message_card.short_description = ""

    def get_form(self, request, obj=None, **kwargs):
        # The config-driven authoring form (type choices + recipient selectors)
        # is only needed while creating. An existing message is read-only.
        messaging_config = SBAdminMessagingService.get_messaging_config(request)
        if messaging_config and obj is None:
            kwargs["form"] = build_message_form_class(messaging_config, request)
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        messaging_config = SBAdminMessagingService.get_messaging_config(request)
        # Recipients are resolved once, at creation; an existing message is
        # read-only so editing never recomputes targeting or recipients.
        if not change:
            if obj.created_by_id is None:
                user = getattr(request, "user", None)
                obj.created_by = user if (user and user.is_authenticated) else None
            if messaging_config:
                targeting = {}
                for audience in getattr(form, "_sbadmin_audiences", []):
                    name = audience_field_name(audience.key)
                    if name in form.cleaned_data:
                        targeting[audience.key] = audience.serialize(
                            form.cleaned_data[name]
                        )
                obj.targeting = targeting
        super().save_model(request, obj, form, change)
        if not change and messaging_config:
            SBAdminMessagingService.sync_recipients(obj, request, messaging_config)


class MessageInboxAdmin(_MessageTypeBadgeMixin, SBAdminNoHistoryDetailMixin, SBAdmin):
    """Per-user inbox over MessageRecipient + notification poll/acknowledge."""

    sbadmin_list_history_enabled = False
    menu_label = _("My messages")

    sbadmin_list_display = (
        SBAdminField(
            name="sender",
            title=_("From"),
            annotate=Coalesce(
                F("message__created_by__email"), Value(""), output_field=TextField()
            ),
            supporting_annotates={
                "sender_first_name": Coalesce(
                    F("message__created_by__first_name"),
                    Value(""),
                    output_field=TextField(),
                ),
                "sender_last_name": Coalesce(
                    F("message__created_by__last_name"),
                    Value(""),
                    output_field=TextField(),
                ),
                "sender_username": Coalesce(
                    F(f"message__created_by__{get_user_model().USERNAME_FIELD}"),
                    Value(""),
                    output_field=TextField(),
                ),
            },
            filter_widget=StringFilterWidget(filter_query_lambda=_sender_filter_query),
        ),
        SBAdminField(
            name="title",
            title=_("Title"),
            annotate=F("message__title"),
            python_formatter=_bold_title_formatter,
        ),
        SBAdminField(
            name="type_badge",
            title=_("Type"),
            annotate=F("message__type"),
        ),
        SBAdminField(
            name="received_at",
            title=_("Received"),
            annotate=F("message__created_at"),
            python_formatter=datetime_formatter,
        ),
        SBAdminField(
            name="read_at",
            title=_("Read"),
            python_formatter=_read_status_badge,
            filter_disabled=True,
        ),
    )
    ordering = ["-message__created_at"]

    sbadmin_fieldsets = [(None, {"fields": ["message_card"]})]
    readonly_fields = ["message_card"]

    # --- permissions: any authenticated user, read-only, own rows only -----

    def has_permission(self, request, obj=None, permission=None):
        if isinstance(permission, SBAdminCustomAction):
            permission = getattr(permission, "permission", None) or "view"
        if permission in ("add", "change", "delete"):
            return False
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated:
            return qs.filter(user=user).select_related("message")
        return qs.none()

    # --- list: titled like the menu, highlight rows but no checkboxes ------

    @sbadmin_action(permission="view")
    def action_list(self, request, *args, **kwargs):
        response = super().action_list(request, *args, **kwargs)
        # Title the list like its menu entry ("My messages") rather than the
        # MessageRecipient model's verbose name.
        if hasattr(response, "context_data"):
            response.context_data["list_title"] = self.get_menu_label()
        return response

    def get_sbadmin_list_selection_actions(self, request):
        # No bulk actions in the inbox.
        return []

    def get_tabulator_definition(self, request):
        # Drop the checkbox-selection column (selectionModule) but keep the
        # "highlight" row hover so rows still read as clickable to the detail.
        definition = super().get_tabulator_definition(request)
        definition["modules"] = [
            module
            for module in definition.get("modules", [])
            if module != "selectionModule"
        ]
        options = definition.get("tabulatorOptions")
        if isinstance(options, dict):
            options["selectableRows"] = "highlight"
        return definition

    # --- detail (read-only message reader) ---------------------------------

    def get_sbadmin_list_actions(self, request):
        # Offer a "New message" action to users allowed to author messages
        # (i.e. who have add permission on the management Message view).
        actions = list(super().get_sbadmin_list_actions(request) or [])
        send_view = self._get_message_send_view(request)
        if send_view is not None and send_view.has_add_permission(request):
            actions.append(new_message_action(send_view, request))
        return actions

    @staticmethod
    def _get_message_send_view(request):
        configuration = getattr(
            getattr(request, "request_data", None), "configuration", None
        )
        if configuration is None:
            return None
        return configuration.view_map.get(SBAdminViewService.get_model_path(Message))

    def get_change_label(self, request, object_id=None):
        # Title the detail page with the sender (message author), not the
        # MessageRecipient's "<message_id> → <user_id>" repr.
        if object_id is not None:
            obj = self.get_object(request, object_id)
            sender = getattr(getattr(obj, "message", None), "created_by", None)
            if sender:
                label = sender.get_full_name() or sender.email or str(sender)
                return f"{_('From')} {label}"
        return super().get_change_label(request, object_id)

    def sender(self, obj_id, value, **additional_data):
        # List "From" column: full name → email (annotated value) → username.
        first = additional_data.get("sender_first_name") or ""
        last = additional_data.get("sender_last_name") or ""
        full_name = f"{first} {last}".strip()
        return full_name or value or additional_data.get("sender_username") or "-"

    def message_card(self, obj):
        return render_message_card(obj.message if obj else None)

    message_card.short_description = ""

    def change_view(self, request, object_id, form_url="", extra_context=None):
        # Opening the detail marks the message as read.
        SBAdminMessagingService.mark_read(request, object_id)
        return super().change_view(request, object_id, form_url, extra_context)

    # --- notification poll + acknowledge -----------------------------------

    @sbadmin_action(permission="view")
    def action_poll_notifications(self, request, modifier, object_id=None):
        messaging_config = SBAdminMessagingService.get_messaging_config(request)
        user = getattr(request, "user", None)
        if not messaging_config or not (user and user.is_authenticated):
            return HttpResponse("")

        pending = list(
            MessageRecipient.objects.filter(
                user=user, notified_at__isnull=True
            ).select_related("message")[:50]
        )
        if not pending:
            return HttpResponse("")

        toasts = []
        modal = None
        notified_ids = []
        for recipient in pending:
            message_type = messaging_config.get_message_type(recipient.message.type)
            if message_type is None:
                continue
            notified_ids.append(recipient.pk)
            if message_type.notification_style == NotificationStyle.MODAL:
                # Show at most one modal per poll; the rest re-surface next poll.
                if modal is None:
                    modal = {
                        "recipient": recipient,
                        "message": recipient.message,
                        "type": message_type,
                        "acknowledge_url": self.get_action_url(
                            "action_acknowledge", "json", object_id=recipient.pk
                        ),
                    }
                else:
                    notified_ids.remove(recipient.pk)
            else:
                toasts.append(
                    {
                        "recipient": recipient,
                        "message": recipient.message,
                        "type": message_type,
                        "detail_url": self.get_detail_url(recipient.pk),
                    }
                )

        if notified_ids:
            MessageRecipient.objects.filter(pk__in=notified_ids).update(
                notified_at=timezone.now()
            )

        html = render_to_string(
            "sb_admin/messaging/poll_response.html",
            {"toasts": toasts, "modal": modal},
            request=request,
        )
        return HttpResponse(html)

    @sbadmin_action(permission="view")
    def action_acknowledge(self, request, modifier, object_id=None):
        SBAdminMessagingService.mark_read(request, object_id)
        # Refresh the page so the inbox / unread badge reflect the read state.
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response
