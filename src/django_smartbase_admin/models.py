from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.querysets import SBAdminListViewConfigurationQueryset


class ColorScheme(models.TextChoices):
    AUTO = "auto", _("System")
    DARK = "dark", _("Dark")
    LIGHT = "light", _("Light")


class SBAdminListViewConfiguration(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255)
    view = models.CharField(max_length=255)
    action = models.CharField(max_length=255, blank=True, null=True)
    modifier = models.CharField(max_length=255, blank=True, null=True)
    url_params = models.TextField()

    objects = SBAdminListViewConfigurationQueryset.as_manager()


class SBAdminUserConfiguration(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    color_scheme = models.CharField(
        max_length=255,
        choices=ColorScheme.choices,
        default=ColorScheme.AUTO,
        verbose_name=_("Theme"),
    )
