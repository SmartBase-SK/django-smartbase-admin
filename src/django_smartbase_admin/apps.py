from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules
from django.conf import settings

from django_smartbase_admin.admin.site import sb_admin_site


class SBAdminConfig(AppConfig):
    name = "django_smartbase_admin"

    def ready(self):
        super().ready()
        from .monkeypatch import fake_inline_monkeypatch
        from .monkeypatch import admin_readonly_field_monkeypatch

        if settings.SB_ADMIN_CONFIGURATION:
            autodiscover_modules("sb_admin", register_to=sb_admin_site)
