from django.conf import settings
from django.db import models

from django_smartbase_admin.querysets import SBAdminListViewConfigurationQueryset


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
