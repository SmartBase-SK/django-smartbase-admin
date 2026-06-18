"""
AppConfig for the messaging app.

Mirrors ``django_smartbase_admin.audit`` — a self-contained, self-registering
feature module. On ``ready()`` it registers the management and per-user inbox
admins with the SBAdmin site.
"""

from django.apps import AppConfig


class SBAdminMessagingConfig(AppConfig):
    """Configuration for the SBAdmin Messaging app."""

    name = "django_smartbase_admin.messaging"
    # Vendor-namespaced label (matches the sibling ``sb_admin_audit`` app) to
    # avoid colliding with a consuming project's own app labels. The URL
    # segment / reverse-name prefix derives from this label.
    label = "sb_admin_messaging"
    verbose_name = "SBAdmin Messaging"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        self._register_sb_admin()

    def _register_sb_admin(self):
        """Register Message + MessageRecipient with SBAdmin."""
        from django_smartbase_admin.admin.site import sb_admin_site
        from django_smartbase_admin.messaging.models import Message, MessageRecipient
        from django_smartbase_admin.messaging.sb_admin import (
            MessageAdmin,
            MessageInboxAdmin,
        )

        if not sb_admin_site.is_registered(Message):
            sb_admin_site.register(Message, MessageAdmin)
        if not sb_admin_site.is_registered(MessageRecipient):
            sb_admin_site.register(MessageRecipient, MessageInboxAdmin)
