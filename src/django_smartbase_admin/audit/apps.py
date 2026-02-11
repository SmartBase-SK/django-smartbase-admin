"""
AppConfig for the audit app.
Installs hooks when Django is ready.
"""
from django.apps import AppConfig


class SBAdminAuditConfig(AppConfig):
    """Configuration for the SBAdmin Audit app."""

    name = "django_smartbase_admin.audit"
    label = "sb_admin_audit"
    verbose_name = "SBAdmin Audit"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Install audit hooks when Django is ready."""
        from django_smartbase_admin.audit.manager import install_manager_hooks

        install_manager_hooks()
        self._register_sb_admin()

    def _register_sb_admin(self):
        """Register AdminAuditLog with SBAdmin."""
        from django_smartbase_admin.admin.site import sb_admin_site
        from django_smartbase_admin.audit.models import AdminAuditLog
        from django_smartbase_admin.audit.sb_admin import AdminAuditLogAdmin

        if not sb_admin_site.is_registered(AdminAuditLog):
            sb_admin_site.register(AdminAuditLog, AdminAuditLogAdmin)
