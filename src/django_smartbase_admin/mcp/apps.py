from django.apps import AppConfig


class MCPConfig(AppConfig):
    """SBAdmin MCP integration.

    Two layers, wired independently by the host project:

    * **MCP transport (always-on)** — ``django-mcp-server`` provides the
      JSON-RPC endpoint; tools are auto-discovered from ``mcp.py`` modules
      across ``INSTALLED_APPS`` (this app ships ``mcp.py`` with
      smoke-test tools and is the place to grow the SBAdmin tool surface).
      Mount via ``include("django_smartbase_admin.mcp.urls")``.

    * **Authentication (pluggable)** — set
      ``DJANGO_MCP_AUTHENTICATION_CLASSES`` to any DRF
      ``BaseAuthentication`` subclass (session, custom JWT, mTLS, IAP, …).
      For a turnkey OAuth 2.1 Authorization Server (Cursor / Claude /
      external IDE clients), additionally include
      ``django_smartbase_admin.mcp.oauth.urls`` and add ``oauth2_provider``
      to ``INSTALLED_APPS``. That submodule wires DOT plus the discovery
      (RFC 8414/9728) and Dynamic Client Registration (RFC 7591)
      endpoints DOT does not ship.
    """

    # Explicit label so it doesn't collide with the unrelated top-level
    # ``mcp`` package (the MCP Python SDK) — Django would otherwise
    # default the label to the last component of ``name`` (``mcp``).
    name = "django_smartbase_admin.mcp"
    label = "sbadmin_mcp"
    verbose_name = "SBAdmin MCP"
    default_auto_field = "django.db.models.BigAutoField"
