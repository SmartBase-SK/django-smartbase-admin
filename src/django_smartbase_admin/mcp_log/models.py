from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class MCPRequestLog(models.Model):
    """One row per MCP tool call: caller, payload, sizes, timing, outcome.

    Written by the ``mcp_tool_called`` receiver in :mod:`logger`.
    """

    timestamp = models.DateTimeField(_("Time"), auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("User"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # ─── What was called ───
    tool_name = models.CharField(_("Tool"), max_length=64, db_index=True)
    arguments = models.JSONField(_("Request"), default=dict, blank=True)

    # ─── Volume ───
    request_size = models.PositiveIntegerField(
        _("Request size (B)"),
        default=0,
        help_text="Serialized size of the input payload in bytes.",
    )
    response_size = models.PositiveIntegerField(
        _("Response size (B)"),
        default=0,
        help_text="Serialized size of the response in bytes.",
    )
    duration_ms = models.PositiveIntegerField(_("Duration (ms)"), default=0)

    # ─── Response shape (meta, not the body) ───
    result_status = models.CharField(_("Result status"), max_length=32, blank=True)
    result_total = models.IntegerField(_("Record count"), null=True, blank=True)
    # Shape of the returned detail (echoed after a read/write), NOT a count of
    # changed values — e.g. a product detail has 42 fields regardless of edit.
    result_fields = models.IntegerField(
        _("Returned field count"), null=True, blank=True
    )
    result_inlines = models.IntegerField(
        _("Returned inline count"), null=True, blank=True
    )
    result_inline_rows = models.IntegerField(
        _("Returned inline rows"), null=True, blank=True
    )

    # ─── Outcome ───
    is_error = models.BooleanField(_("Error"), default=False, db_index=True)
    error_type = models.CharField(_("Error type"), max_length=128, blank=True)
    error_message = models.TextField(_("Error message"), blank=True)

    class Meta:
        app_label = "sbadmin_mcp_log"
        db_table = "sbadmin_mcp_log_request"
        verbose_name = "MCP Request Log"
        verbose_name_plural = "MCP Request Logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["tool_name", "timestamp"]),
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["is_error", "timestamp"]),
        ]

    def __str__(self):
        outcome = "error" if self.is_error else "ok"
        return f"{self.timestamp} - {self.user} - {self.tool_name} ({outcome})"

    @classmethod
    def prune(cls, days):
        """Delete rows older than ``days``; return the count deleted."""
        cutoff = timezone.now() - timezone.timedelta(days=days)
        qs = cls.objects.filter(timestamp__lt=cutoff)
        return qs._raw_delete(qs.db)
