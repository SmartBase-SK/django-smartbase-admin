"""SBAdmin registrations for the messaging feature.

- :class:`MessageAdmin` — management UI for authoring messages, gated by Django
  model permissions. Builds a config-driven form (type + audience selection) and
  syncs recipients on save; shows per-recipient read status.
- :class:`MessageInboxAdmin` — per-user inbox over ``MessageRecipient``. Visible
  to any authenticated (staff) user, scoped to their own rows. Opening a message
  marks it read, and it hosts the notification poll + acknowledge endpoints.
"""

from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.engine.actions import SBAdminCustomAction, sbadmin_action
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import datetime_formatter
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
from django_smartbase_admin.messaging.services import (
    get_messaging_config,
    sync_recipients,
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


class MessageRecipientStatusInline(SBAdminTableInline):
    """Read-only listing of recipients + their read status ("who hasn't read")."""

    model = MessageRecipient
    fields = ["user", "notified_at", "read_at"]
    readonly_fields = ["user", "notified_at", "read_at"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MessageAdmin(SBAdmin):
    """Management UI for authoring/editing messages (Django model perms)."""

    form = MessageForm
    sbadmin_list_history_enabled = False

    sbadmin_list_display = (
        SBAdminField(name="title", title=_("Title")),
        SBAdminField(name="type", title=_("Type")),
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

    def get_sbadmin_fieldsets(self, request, object_id=None):
        # Created message → single read-only detail card. Otherwise the editable
        # authoring form (content fields + recipient selectors on the right).
        if object_id is not None:
            return [(None, {"fields": ["message_card"]})]
        fieldsets = [(None, {"fields": ["title", "type", "content"]})]
        messaging_config = get_messaging_config(request)
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
        messaging_config = get_messaging_config(request)
        if messaging_config and obj is None:
            kwargs["form"] = build_message_form_class(messaging_config, request)
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        messaging_config = get_messaging_config(request)
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
            sync_recipients(obj, request, messaging_config)


class MessageInboxAdmin(SBAdmin):
    """Per-user inbox over MessageRecipient + notification poll/acknowledge."""

    sbadmin_list_history_enabled = False
    menu_label = _("My messages")

    sbadmin_list_display = (
        SBAdminField(
            name="title",
            title=_("Title"),
            annotate=F("message__title"),
            filter_disabled=True,
        ),
        SBAdminField(
            name="type",
            title=_("Type"),
            annotate=F("message__type"),
            filter_disabled=True,
        ),
        SBAdminField(
            name="received_at",
            title=_("Received"),
            annotate=F("message__created_at"),
            python_formatter=datetime_formatter,
            filter_disabled=True,
        ),
        SBAdminField(name="read_at", title=_("Read"), filter_disabled=True),
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

    def message_card(self, obj):
        return render_message_card(obj.message if obj else None)

    message_card.short_description = ""

    def change_view(self, request, object_id, form_url="", extra_context=None):
        # Opening the detail marks the message as read.
        self._mark_read(request, object_id)
        return super().change_view(request, object_id, form_url, extra_context)

    def _mark_read(self, request, recipient_pk):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return
        MessageRecipient.objects.filter(
            pk=recipient_pk, user=user, read_at__isnull=True
        ).update(read_at=timezone.now())

    # --- notification poll + acknowledge -----------------------------------

    @sbadmin_action(permission="view")
    def action_poll_notifications(self, request, modifier, object_id=None):
        messaging_config = get_messaging_config(request)
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
        self._mark_read(request, object_id)
        return HttpResponse("")
