from django.apps import AppConfig


class MCPLogConfig(AppConfig):
    """Optional MCP request logging.

    Opt-in via ``INSTALLED_APPS``; ``ready()`` connects the logger to
    ``mcp_tool_called`` and registers the admin view. The host project
    schedules retention (``MCPRequestLog.prune``).
    """

    name = "django_smartbase_admin.mcp_log"
    label = "sbadmin_mcp_log"
    verbose_name = "SBAdmin MCP Log"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django_smartbase_admin.admin.site import sb_admin_site
        from django_smartbase_admin.mcp.signals import mcp_tool_called
        from django_smartbase_admin.mcp_log.models import MCPRequestLog
        from django_smartbase_admin.mcp_log.logger import on_mcp_tool_called
        from django_smartbase_admin.mcp_log.sb_admin import MCPRequestLogAdmin

        mcp_tool_called.connect(
            on_mcp_tool_called, dispatch_uid="sbadmin_mcp_log_logger"
        )

        if not sb_admin_site.is_registered(MCPRequestLog):
            sb_admin_site.register(MCPRequestLog, MCPRequestLogAdmin)
