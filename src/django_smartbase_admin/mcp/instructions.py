"""Default MCP server instructions for host projects.

Set ``DJANGO_MCP_GLOBAL_SERVER_CONFIG["instructions"]`` to
``SBADMIN_MCP_SERVER_INSTRUCTIONS``. Host projects may append their own
deployment-specific text to that setting if needed.
"""

SBADMIN_MCP_SERVER_INSTRUCTIONS = """\
SBAdmin MCP — same permissions and validation as the UI.

Workflow: ``list_admins`` (discover ``view_id``, columns, filters, inlines) →
``list_rows`` / ``fetch_detail`` / ``fetch_add_form`` → ``autocomplete`` for
labels → ``create_object`` or ``update_detail``.

Rules: copy ``widget_id`` only from prior tool output (never invent it).
``list_rows`` requires non-empty ``fields``. Write results:
``{"status": "ok", ...}`` or ``{"status": "invalid", "errors": ...}`` (no DB change).
Inline dict keys use ``inline_name`` from ``list_admins`` (inline class name).
Create flow: ``fetch_add_form`` then ``create_object``; inline FK ids on add often
need ``autocomplete`` on another admin with the same ``filter.target_model``.
"""
