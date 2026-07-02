"""Messaging service: config access, badges, recipient resolution + read state."""

from django.utils import timezone

from django_smartbase_admin.engine.field_formatter import format_badge
from django_smartbase_admin.messaging.models import (
    Message,
    MessageAttachment,
    MessageRecipient,
)


class SBAdminMessagingService:
    RECIPIENT_SYNC_BATCH_SIZE = 2000

    @classmethod
    def get_messaging_config(cls, request):
        """Return the active ``SBAdminMessagingConfig`` for the request, or ``None``.

        Messaging is enabled by setting ``messaging_config`` on the project's
        ``SBAdminRoleConfiguration``.
        """
        request_data = getattr(request, "request_data", None)
        configuration = getattr(request_data, "configuration", None)
        return getattr(configuration, "messaging_config", None)

    @classmethod
    def mark_read(cls, request, recipient_pk):
        """Mark a recipient row as read for the request's user, if currently unread."""
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return
        MessageRecipient.objects.filter(
            pk=recipient_pk, user=user, read_at__isnull=True
        ).update(read_at=timezone.now())

    @classmethod
    def render_message_type_badge(cls, type_key, messaging_config):
        """Render an SBAdmin badge for a message type.

        Uses the configured type's colour + label; for an unknown/custom type
        (one with no configured badge) falls back to the "info" type's badge
        styling, keeping the raw type key as the label.
        """
        message_type = (
            messaging_config.get_message_type(type_key) if messaging_config else None
        )
        if message_type is not None:
            return format_badge(message_type.label, message_type.color)
        info_type = (
            messaging_config.get_message_type("info") if messaging_config else None
        )
        color = info_type.color if info_type else "notice"
        return format_badge(type_key, color)

    @classmethod
    def get_unread_count(cls, request):
        """Return the count of unread messages for the request's user.

        Designed to be passed straight to an ``SBAdminMenuItem``'s ``badge``
        argument so the inbox menu entry shows an unread-message badge::

            SBAdminMenuItem(
                view_id="sb_admin_messaging_messagerecipient",
                label=_("My messages"),
                icon="Mail",
                badge=SBAdminMessagingService.get_unread_count,
            )

        Returns ``0`` when messaging is disabled or the user is anonymous, which
        renders no badge.
        """
        if not cls.get_messaging_config(request):
            return 0
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return 0
        return MessageRecipient.objects.filter(user=user, read_at__isnull=True).count()

    @classmethod
    def get_poller_context(cls, request):
        """Build the global-context keys driving the notification poller.

        Returns ``{}`` when messaging is disabled or the user is anonymous.
        """
        messaging_config = cls.get_messaging_config(request)
        if not messaging_config:
            return {}
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return {}

        from django.urls import NoReverseMatch, reverse

        from django_smartbase_admin.services.views import SBAdminViewService

        inbox_id = SBAdminViewService.get_model_path(MessageRecipient)
        try:
            poll_url = reverse(
                "sb_admin:sb_admin_base",
                kwargs={
                    "view": inbox_id,
                    "action": "action_poll_notifications",
                    "modifier": "json",
                },
            )
        except NoReverseMatch:
            return {}
        return {
            "sbadmin_messaging_poll_url": poll_url,
            "sbadmin_messaging_poll_interval": messaging_config.poll_interval_seconds,
        }

    @classmethod
    def resolve_target_user_ids(cls, message, request, messaging_config):
        """Resolve a message's ``targeting`` blob into a set of user ids."""
        user_ids = set()
        for audience_key, stored_value in (message.targeting or {}).items():
            audience = messaging_config.get_audience(audience_key)
            if audience is None:
                continue
            user_ids.update(
                audience.resolve_users(stored_value, request).values_list(
                    "pk", flat=True
                )
            )
        return user_ids

    @classmethod
    def add_recipients(cls, message, user_ids):
        """Create ``MessageRecipient`` rows for ``user_ids`` that don't have one.

        Idempotent: skips ids that already have a row and relies on the
        ``(message, user)`` unique constraint (``ignore_conflicts``) as a
        backstop, so it is safe to call repeatedly. Returns the number created.
        """
        user_ids = set(user_ids or [])
        if not user_ids:
            return 0
        existing = set(message.recipients.values_list("user_id", flat=True))
        to_create = [
            MessageRecipient(message=message, user_id=user_id)
            for user_id in user_ids
            if user_id not in existing
        ]
        if not to_create:
            return 0
        MessageRecipient.objects.bulk_create(
            to_create,
            batch_size=cls.RECIPIENT_SYNC_BATCH_SIZE,
            ignore_conflicts=True,
        )
        return len(to_create)

    @classmethod
    def create_message(
        cls,
        *,
        title,
        type,
        content="",
        targeting=None,
        created_by=None,
        request=None,
        messaging_config=None,
        user_ids=None,
        attachments=None,
    ):
        """Author a message and its recipients — the entry point for code.

        Use this anywhere outside the admin (management commands, signals, other
        services) so message creation goes through one code path. The recipients
        are the union of:

        * ``user_ids`` — an explicit iterable of user ids, and
        * the users resolved from ``targeting`` via ``messaging_config``'s
          audiences. ``request`` is forwarded to each audience's
          ``resolve_users`` and may be required by custom audiences; pass
          explicit ``user_ids`` instead when no request/config is available.

        ``attachments`` is an optional iterable of Django ``File`` objects (each
        must carry a name, e.g. an ``UploadedFile`` or a named ``ContentFile``).

        Returns the created :class:`~django_smartbase_admin.messaging.models.Message`.
        """
        message = Message.objects.create(
            title=title,
            type=type,
            content=content or "",
            targeting=targeting or {},
            created_by=created_by,
        )
        recipient_ids = set(user_ids or [])
        if messaging_config and message.targeting:
            recipient_ids |= set(
                cls.resolve_target_user_ids(message, request, messaging_config)
            )
        cls.add_recipients(message, recipient_ids)
        for attachment in attachments or []:
            MessageAttachment.objects.create(message=message, file=attachment)
        return message
