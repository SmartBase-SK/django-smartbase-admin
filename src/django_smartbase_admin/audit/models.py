from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class AdminAuditLog(models.Model):
    """Complete audit log for admin operations."""

    class ActionType(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        BULK_CREATE = "bulk_create", "Bulk Create"
        BULK_UPDATE = "bulk_update", "Bulk Update"
        BULK_DELETE = "bulk_delete", "Bulk Delete"

    # ─── Metadata ───
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    request_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Groups changes from the same request together",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # ─── What changed (primary object) ───
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    object_id = models.TextField(blank=True)
    object_repr = models.CharField(max_length=255)

    # ─── Parent context (for inline edits) ───
    parent_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    parent_object_id = models.TextField(blank=True)
    parent_object_repr = models.CharField(max_length=255, blank=True)

    # ─── Action ───
    action_type = models.CharField(max_length=20, choices=ActionType.choices)

    # ─── Change data ───
    snapshot_before = models.JSONField(default=dict, blank=True)
    changes = models.JSONField(default=dict, blank=True)

    # ─── Bulk operation ───
    is_bulk = models.BooleanField(default=False, db_index=True)
    bulk_count = models.IntegerField(default=0)

    # ─── Affected objects (FK/M2M targets for reverse lookups) ───
    # JSON array: [{"ct": "app.model", "id": 1, "repr": "Name"}, ...]
    # Allows tracking multiple types of affected objects
    affected_objects = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "sb_admin_audit"
        db_table = "sb_admin_audit_log"
        verbose_name = "Admin Audit Log"
        verbose_name_plural = "Admin Audit Logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["parent_content_type", "parent_object_id"]),
            GinIndex(fields=["affected_objects"]),  # Fast JSON contains queries
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["action_type"]),
        ]

    def __str__(self):
        return (
            f"{self.timestamp} - {self.user} - {self.action_type} - {self.object_repr}"
        )
