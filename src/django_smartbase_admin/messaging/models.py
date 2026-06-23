import os

from ckeditor.fields import RichTextField
from django.conf import settings
from django.core.files.storage import default_storage, storages
from django.db import models
from django.utils.translation import gettext_lazy as _


class Message(models.Model):
    """A message authored in the admin and delivered to a set of users.

    Kept as a standalone domain entity (not folded into the notification/popup
    layer) so the system can grow into a fuller messaging product — e.g. a
    future ``parent`` self-FK for replies/threads — without reshaping anything.
    ``created_by`` is the *author*; nothing here assumes the author is staff,
    only the management view's permissions restrict who can create today.
    """

    title = models.CharField(max_length=255, verbose_name=_("Title"))
    # Stores a message-type key defined in the project's messaging config.
    type = models.CharField(max_length=64, verbose_name=_("Type"))
    content = RichTextField(verbose_name=_("Content"), blank=True)
    # {audience_key: <serialized selection>} — kept for re-edit and re-resolution.
    targeting = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        app_label = "sb_admin_messaging"
        ordering = ["-created_at"]
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")

    def __str__(self):
        return self.title


DEFAULT_MESSAGE_ATTACHMENT_UPLOAD_TO = "messaging/attachments/"


def message_attachment_upload_to(instance, filename):
    """Resolve the upload directory for a message attachment.

    This is a stable, module-level callable on purpose: Django serializes a
    callable ``upload_to`` into migrations as its dotted import path and never
    inspects what it returns. So projects can repoint attachment storage via the
    ``SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO`` setting — a string prefix, an
    empty string to store at the storage/container root, or their own
    ``(instance, filename) -> path`` callable — *without* generating a migration,
    since only this function's runtime result changes, not the field definition.
    Defaults to ``messaging/attachments/`` when unset.
    """
    override = getattr(settings, "SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO", None)
    if callable(override):
        return override(instance, filename)
    # ``None`` (unset) → default prefix; an explicit ``""`` → container root,
    # since ``os.path.join("", filename) == filename``.
    base = DEFAULT_MESSAGE_ATTACHMENT_UPLOAD_TO if override is None else override
    return os.path.join(base, filename)


def message_attachment_storage():
    """Resolve the storage backend for message attachments.

    A callable ``storage`` is deconstructed by Django as its import path (the
    backend it returns is never inspected), so — exactly like
    :func:`message_attachment_upload_to` — projects can swap the backend via the
    ``SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE`` setting *without* a migration. The
    setting accepts a key into ``STORAGES``, a ``Storage`` instance, or a
    callable returning one. Defaults to the project's default storage when unset.
    """
    override = getattr(settings, "SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE", None)
    if override is None:
        return default_storage
    if isinstance(override, str):
        return storages[override]
    if callable(override):
        return override()
    return override


class MessageAttachment(models.Model):
    message = models.ForeignKey(
        Message,
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    file = models.FileField(
        upload_to=message_attachment_upload_to,
        storage=message_attachment_storage,
        verbose_name=_("File"),
    )

    class Meta:
        app_label = "sb_admin_messaging"
        verbose_name = _("Attachment")
        verbose_name_plural = _("Attachments")

    @property
    def filename(self):
        """Base file name without the upload directory path."""
        return os.path.basename(self.file.name) if self.file else ""

    def __str__(self):
        return self.filename or f"Attachment #{self.pk}"


class MessageRecipient(models.Model):
    """Per-(message, user) delivery + read state — the source of truth for
    "who receives" a message. A clean join that can later generalize into a
    conversation participant without breaking the popup/read logic.
    """

    message = models.ForeignKey(
        Message,
        related_name="recipients",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    # When the toast/modal popup was shown — stops it re-firing on every poll.
    notified_at = models.DateTimeField(null=True, blank=True)
    # When the user opened the detail / acknowledged — drives the unread view.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "sb_admin_messaging"
        unique_together = ("message", "user")
        verbose_name = _("Message recipient")
        verbose_name_plural = _("Message recipients")

    def __str__(self):
        return self.message.title if self.message_id else _("Message")
