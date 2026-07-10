"""Default MCP server instructions for host projects.

Set ``DJANGO_MCP_GLOBAL_SERVER_CONFIG["instructions"]`` to
``SBADMIN_MCP_SERVER_INSTRUCTIONS``. Host projects may append their own
deployment-specific text to that setting if needed.
"""

SBADMIN_MCP_SERVER_INSTRUCTIONS = """\
SBAdmin MCP — read and manage admin records with the same permissions and
validation as the UI. You only ever see and act on what the user's account is
allowed to.

What you can do:
* Discover the available admin views and, per view, their columns, filters,
  detail fields, inlines, filter presets, and actions (``list_admins``).
* Browse: filter (text, choice, boolean, number range, date range,
  related-record), full-text search, sort, and paginate (``list_rows``).
* Apply a named or saved filter preset and replay it (``fetch_filter_preset``).
* Read one record in full, with related (inline) rows and detail widgets
  (``fetch_detail``).
* Read parent-scoped list widgets with ``list_rows`` using the widget
  ``view_id`` and ``parent_object_id`` from ``fetch_detail.widgets``; read
  non-list widgets with ``fetch_widget_data``.
* Look up a related record by name to get its id — for filtering by it or
  setting it on a create/update form (``autocomplete``).
* Create, update, and delete records — including their related rows
  (``create_object`` / ``update_detail`` / ``delete_objects``).
* Run actions on a row, a detail page, the whole list, a selection, or an
  inline row (``invoke_*_action``); inspect a modal action's form first with
  ``fetch_action_form``. Object-only fieldset actions are discovered from
  ``fetch_detail.detail_actions``. Submit declared action formsets through
  ``formset_values`` using the names returned by ``fetch_action_form``.
* Export a list or selection to a file.

Safety: deletes and impactful actions return ``needs_confirmation`` with a
preview first; re-call with ``confirmed=True`` to commit.

Workflow: ``list_admins`` (discover ``view_id``, columns, filters, inlines) →
``list_rows`` / ``fetch_detail`` / ``fetch_add_form`` → ``autocomplete`` for
labels → ``create_object`` or ``update_detail``.

Rules: copy ``widget_id`` only from prior tool output (never invent it).
``list_rows`` requires non-empty ``fields``. Write results:
``{"status": "ok", ...}`` or ``{"status": "invalid", "errors": ...}`` (no DB change).
Inline dict keys use ``inline_name`` from ``list_admins`` (inline class name).
Send nested arguments (``inlines``, ``field_values``, ``formset_values``,
``object_ids``, ``filter_data``, ``sort``) as real JSON objects/arrays, never
stringified JSON; pass ids as JSON numbers exactly as returned (e.g. ``174``,
not ``"174"``) so rows match.
Create flow: ``fetch_add_form`` then ``create_object``; inline FK ids on add often
need ``autocomplete`` on another admin with the same ``filter.target_model``.

Custom dashboard: to build a local, single-user dashboard — any creative live
view of this data (metrics, tables, charts/graphs) — read the
``dashboard://blueprint`` resource (setup is in its description). If the host
also exposes the MCP-endpoint-prefixed REST route, e.g.
``POST mcp/rest/tools/list_rows/``, and an authenticated probe succeeds, the
dashboard can use that REST endpoint for live list data. If the probe
returns 401 or the URL is unavailable, do not propose the REST dashboard path;
``SBADMIN_MCP_REST_AUTHENTICATOR`` is probably not configured for that project.
"""
