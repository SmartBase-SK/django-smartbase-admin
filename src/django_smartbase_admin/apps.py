from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules
from django.conf import settings


class SBAdminConfig(AppConfig):
    name = "django_smartbase_admin"
    default_auto_field = "django.db.models.AutoField"
    default_site = "django_smartbase_admin.admin.site.SBAdminSite"

    def ready(self):
        super().ready()
        from .monkeypatch import fake_inline_monkeypatch
        from .monkeypatch import admin_readonly_field_monkeypatch
        from django_smartbase_admin.admin.site import sb_admin_site

        if settings.SB_ADMIN_CONFIGURATION:
            autodiscover_modules("sb_admin", register_to=sb_admin_site)

        # Register Django system checks (sbadmin.W001..W003). Imported after
        # autodiscover so the checks see every registered admin.
        from . import checks  # noqa: F401

        from django.core.signals import request_finished
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        request_finished.connect(
            SBAdminThreadLocalService.clear_request,
            dispatch_uid="sbadmin_clear_request_contextvar",
        )
