"""Default MCP server instructions for host projects.

Set ``DJANGO_MCP_GLOBAL_SERVER_CONFIG["instructions"]`` to
``SBADMIN_MCP_SERVER_INSTRUCTIONS``. Clients may truncate instructions
(Claude Code keeps 2048 characters), so keep any host appendix short and put
per-view rules into that view's ``mcp_description``, which ``list_admins``
returns in full.
"""

SBADMIN_MCP_SERVER_INSTRUCTIONS = """\
SBAdmin MCP: read and manage admin records with the user's own permissions
and the same validation as the UI. You only see what their account may.

Workflow:
1. ``list_admins(detail="index")`` to find the ``view_id``, then
   ``list_admins(view_id=...)`` for its columns, filters, presets and
   actions. Never read every view in full: the payload is huge.
2. Read with ``list_rows`` or ``fetch_detail``. ``autocomplete`` turns a
   name into an id for a filter or a form field.
3. Write with ``create_object`` (after ``fetch_add_form``) or
   ``update_detail``. Run actions with the ``invoke_*_action`` tools,
   calling ``fetch_action_form`` first for ``kind == "modal"``. Methods
   listed only under ``mcp_actions`` run with ``invoke_action``.

Rules:
* Deletes and impactful actions answer ``needs_confirmation`` with a preview
  first. Show it to the user, then repeat the call with ``confirmed=true``.
* Copy ``view_id``, ``widget_id``, ``action_id`` and ``inline_name`` from
  tool output. Never construct them.
* Send nested arguments as JSON objects and arrays, not strings, and ids as
  JSON numbers exactly as returned (``174``, not ``"174"``).
* ``{"status": "invalid"}`` means nothing was written. Fix and retry.
* ``value_available=false`` means a value was withheld. ``write_only=true``
  means you may set it but must not read the returned ``null`` as its value.

Local live dashboards: read the ``dashboard://blueprint`` resource.
"""
