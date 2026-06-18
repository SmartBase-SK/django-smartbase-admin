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
from django_smartbase_admin.engine.field import SBAdminField
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
        messaging_config = get_messaging_config(request)
        audience_fields = []
        if messaging_config:
            for audience in messaging_config.audiences:
                if audience.get_form_field(request) is not None:
                    audience_fields.append(audience_field_name(audience.key))
        fieldsets = [(None, {"fields": ["title", "type", "content"]})]
        if audience_fields:
            fieldsets.append((_("Recipients"), {"fields": audience_fields}))
        return fieldsets

    def get_form(self, request, obj=None, **kwargs):
        messaging_config = get_messaging_config(request)
        if messaging_config:
            kwargs["form"] = build_message_form_class(messaging_config, request)
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        messaging_config = get_messaging_config(request)
        if not change and obj.created_by_id is None:
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
        if messaging_config:
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
            filter_disabled=True,
        ),
        SBAdminField(name="read_at", title=_("Read"), filter_disabled=True),
    )
    ordering = ["-message__created_at"]

    sbadmin_fieldsets = [
        (
            None,
            {"fields": ["message_title", "message_content", "message_attachments"]},
        ),
    ]
    readonly_fields = ["message_title", "message_content", "message_attachments"]

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

    # --- detail (read-only message reader) ---------------------------------

    def message_title(self, obj):
        return obj.message.title if obj else "-"

    message_title.short_description = _("Title")

    def message_content(self, obj):
        from django.utils.safestring import mark_safe

        return mark_safe(obj.message.content) if obj else "-"

    message_content.short_description = _("Content")

    def message_attachments(self, obj):
        from django.utils.safestring import mark_safe

        if not obj:
            return "-"
        return mark_safe(
            render_to_string(
                "sb_admin/messaging/attachments.html",
                {"attachments": obj.message.attachments.all()},
            )
        )

    message_attachments.short_description = _("Attachments")

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
