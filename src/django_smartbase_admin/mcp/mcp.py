"""``SBAdminTools`` — autodiscovery entry point for ``django-mcp-server``.

Discovered as ``<app>.mcp`` (here: ``django_smartbase_admin.mcp.mcp``);
each public method on an ``MCPToolset`` subclass becomes one MCP tool.

Tool methods stay thin — orchestration only — and delegate to:

* ``bridge``    — DRF/MCP request <-> SBAdmin pipeline.
* ``resolvers`` — agent identifier -> SBAdmin object.
* ``schema``    — ``list_admins`` discovery payload.

``self.request`` is the live DRF request; ``self.request.user`` is
whoever ``DJANGO_MCP_AUTHENTICATION_CLASSES`` resolved.
"""

from __future__ import annotations

import json

from django.core.exceptions import PermissionDenied
from django.http import Http404
from mcp_server import MCPToolset

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.const import (
    Action,
    ADVANCED_FILTER_DATA_NAME,
    AUTOCOMPLETE_FORWARD_NAME,
    AUTOCOMPLETE_PAGE_NUM,
    AUTOCOMPLETE_SEARCH_NAME,
    BASE_PARAMS_NAME,
    COLUMNS_DATA_NAME,
    FILTER_DATA_NAME,
    TABLE_PARAMS_SELECTED_FILTER_TYPE,
    SB_ADMIN_AJAX_NOTIFICATIONS_KEY,
    TABLE_PARAMS_FULL_TEXT_SEARCH,
    TABLE_PARAMS_NAME,
    TABLE_PARAMS_PAGE_NAME,
    TABLE_PARAMS_SIZE_NAME,
    TABLE_PARAMS_SORT_NAME,
)
from django_smartbase_admin.mcp.actions import (
    SBAdminMCPActionFormService,
    SBAdminMCPActionInvokeService,
)
from django_smartbase_admin.mcp.service import SBAdminMCPDetailService
from django_smartbase_admin.mcp.bridge import (
    build_columns_data,
    ensure_sbadmin_request_data,
    set_request_payload,
    strip_html_cells,
)
from django_smartbase_admin.mcp.inlines import attach_inlines
from django_smartbase_admin.mcp.resolvers import resolve_admin
from django_smartbase_admin.mcp.actions import ACTION_INVOKERS
from django_smartbase_admin.mcp.schema import admin_entry, get_widget_shapes
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.views import SBAdminViewService


def _widgets_by_filter_field(admin, request, field_map=None) -> dict:
    """Map of ``filter_field -> filter_widget`` for filterable columns.

    ``field_map`` lets the caller pass an already-built map so
    ``get_field_map`` (which rebuilds + clones every field) isn't run
    again; falls back to fetching one when omitted.
    """
    if field_map is None:
        field_map = admin.get_field_map(request)
    mapping: dict = {}
    for field in (field_map or {}).values():
        if getattr(field, "filter_disabled", False):
            continue
        widget = getattr(field, "filter_widget", None)
        if widget is None:
            continue
        mapping[getattr(field, "filter_field", None) or field.name] = widget
    return mapping


def _validate_filter_data(
    admin, request, filter_data: dict | None, field_map=None
) -> None:
    """Reject unknown filter keys and wrong-shape values up front so the
    agent sees a clear ``invalid`` instead of an ambiguous empty result.
    """
    if not filter_data:
        return
    widgets = _widgets_by_filter_field(admin, request, field_map)
    unknown = [k for k in filter_data if k not in widgets]
    if unknown:
        raise ValueError(
            f"Unknown filter key(s) {unknown!r}. "
            f"Known filters on {admin.get_id()!r}: {sorted(widgets)}"
        )
    for key, value in filter_data.items():
        widgets[key].validate_value(value)


def _normalize_filter_keys(filter_data: dict | None, field_map) -> dict | None:
    """Re-key ``filter_data`` to the ``filter_field`` the list pipeline uses,
    accepting either a column ``name`` (the same identifier ``fields`` and
    ``sort`` take) or the ``filter_field`` itself.

    This lets the agent use one identifier — the column name — everywhere,
    instead of tracking that a column's filter key often differs. An exact
    ``filter_field`` match wins, so saved presets (whose keys are already
    ``filter_field``) replay unchanged and a column name that happens to
    collide with another column's filter_field stays unambiguous.
    Unrecognised keys pass through so ``_validate_filter_data`` reports them.
    """
    if not filter_data:
        return filter_data
    name_to_filter = {
        name: (getattr(f, "filter_field", None) or name)
        for name, f in (field_map or {}).items()
    }
    filter_fields = set(name_to_filter.values())
    normalized: dict = {}
    for key, value in filter_data.items():
        if key in filter_fields:
            normalized[key] = value
        elif key in name_to_filter:
            normalized[name_to_filter[key]] = value
        else:
            normalized[key] = value
    return normalized


def _filter_keys_to_names(filter_data: dict | None, field_map) -> dict | None:
    """Inverse of :func:`_normalize_filter_keys`: re-key filter_data from the
    stored ``filter_field`` form back to the column ``name``.

    A decoded preset's keys are ``filter_field``-shaped (that's how the list
    action stores them); rewriting them to the column ``name`` means a fetched
    preset speaks the same single identifier as the schema and ``list_rows``,
    so the agent never has to recognise a ``filter_field`` it can't find in
    ``list_admins``. A ``filter_field`` with no matching column is left as-is
    (it still round-trips through ``_normalize_filter_keys`` unchanged); when
    several columns share one ``filter_field`` the first is used — they
    normalize back to the same key, so the choice is immaterial.
    """
    if not filter_data:
        return filter_data
    filter_to_name: dict = {}
    for name, f in (field_map or {}).items():
        filter_to_name.setdefault(getattr(f, "filter_field", None) or name, name)
    return {filter_to_name.get(key, key): value for key, value in filter_data.items()}


def _validate_sort(admin, request, sort, field_map=None) -> None:
    """Reject unknown sort fields up front with the same clean, listed
    error ``filter_data`` / ``fields`` give. Without this an unknown
    column falls through to the ORM and surfaces a raw Django
    ``FieldError`` that leaks internal model field names.
    """
    if not sort:
        return
    if field_map is None:
        field_map = admin.get_field_map(request)
    field_map = field_map or {}
    for entry in sort:
        if not isinstance(entry, dict) or "field" not in entry:
            raise ValueError(
                "Each sort entry must be {'field': <name>, 'dir': "
                f"'asc'|'desc'}}, got {entry!r}"
            )
        name = entry["field"]
        if name not in field_map:
            raise LookupError(
                f"Admin {admin.get_id()!r} cannot sort by {name!r}; "
                f"sortable fields: {sorted(field_map)}."
            )
        direction = entry.get("dir", "asc")
        if direction not in ("asc", "desc"):
            raise ValueError(f"sort dir must be 'asc' or 'desc', got {direction!r}")


def _decode_preset_url_params(url_params) -> dict:
    """Turn a preset's raw ``url_params`` blob (JSON string or dict) into
    the kwargs ``list_rows`` accepts: ``filter_data``,
    ``full_text_search``, ``sort``, ``page_size``.

    Empty / missing pieces are simply absent from the returned dict so
    the agent can splat the result onto ``list_rows`` without filtering
    out ``None``s.

    Empty filter values are dropped. Presets pad ``filterData`` with an
    empty ``""`` for every unfiltered column (so the UI renders all the
    filter inputs); those placeholders aren't real filters and would in
    fact fail ``list_rows``' per-widget validation (e.g. a multichoice
    widget rejects ``""`` — it wants a list). Stripping them leaves only
    the columns the preset actually constrains. Non-empty values are
    left in their stored widget form (e.g. autocomplete /multichoice
    ``[{"value", "label"}]``); ``list_rows`` accepts that shape directly.

    ``page`` is intentionally dropped — a saved preset's last-viewed
    page is session state, not part of the preset; an agent replaying it
    should start from page 1 (the ``list_rows`` default).
    """
    if isinstance(url_params, str):
        url_params = json.loads(url_params) if url_params else {}
    url_params = url_params or {}
    raw_filter = dict(url_params.get(FILTER_DATA_NAME, {}) or {})
    # Some presets store a multi-value filter as a JSON string; parse it back
    # to a list. Plain scalar strings (substring filters) are left untouched.
    for _key, _value in list(raw_filter.items()):
        if isinstance(_value, str) and _value[:1] in "[{":
            try:
                raw_filter[_key] = json.loads(_value)
            except ValueError:
                pass
    table_params = url_params.get(TABLE_PARAMS_NAME, {}) or {}

    # Advanced-filter presets keep their predicates in advancedFilterData,
    # which list_rows doesn't apply — decoding only the simple filterData
    # would match too many rows. Refuse rather than hand back a filter that
    # silently under-constrains.
    if url_params.get(ADVANCED_FILTER_DATA_NAME) or raw_filter.get(
        TABLE_PARAMS_SELECTED_FILTER_TYPE
    ):
        raise ValueError(
            "This preset uses advanced filters, which list_rows does not "
            "support; rebuild the filter with list_rows filter_data instead."
        )

    decoded: dict = {}
    # ``sb_admin_full_search`` lives inside filterData (it's how the list
    # action reads it) — surface it as a dedicated arg here.
    full_text = raw_filter.pop(TABLE_PARAMS_FULL_TEXT_SEARCH, None)
    # Drop padding placeholders: "", None, [] and {} all mean "no filter".
    filter_data = {k: v for k, v in raw_filter.items() if v not in ("", None, [], {})}
    if filter_data:
        decoded["filter_data"] = filter_data
    if full_text:
        decoded["full_text_search"] = full_text
    if TABLE_PARAMS_SORT_NAME in table_params:
        decoded["sort"] = table_params[TABLE_PARAMS_SORT_NAME]
    if TABLE_PARAMS_SIZE_NAME in table_params:
        decoded["page_size"] = int(table_params[TABLE_PARAMS_SIZE_NAME])
    return decoded


def _guarded_tool_call(method):
    """Tool entry/exit wrapper.

    Before the tool runs, enforce the admin staff gate. MCP tools never
    pass through ``SBAdminSite.admin_view()``, so without this a user with
    Django model permissions but no admin access (``is_active``/``is_staff``)
    could read and mutate through the tools — the same boundary the HTTP
    admin's front door applies.

    After the tool runs, clear the bridge-bound thread-local request.
    ``ensure_sbadmin_request_data`` binds it for the duration of the call so
    SBAdmin internals (and the audit hook) see the active request, but MCP
    transport never fires ``request_finished`` — without this the binding
    leaks across calls and tests, causing audit rows to be written under
    stale users.
    """
    from functools import wraps

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        if not sb_admin_site.has_permission(self.request):
            raise PermissionDenied
        try:
            return method(self, *args, **kwargs)
        finally:
            SBAdminThreadLocalService.clear_request()

    return wrapper


class SBAdminTools(MCPToolset):
    """Tools over the SBAdmin admin surface.

    Every tool runs as the authenticated user — same permissions, row
    isolation, and filters they'd see in the UI.

    Typical flow:
      1. ``list_admins`` once per session for ``view_id``s, field /
         filter / inline handles, and ``widget_id``s.
      2. ``autocomplete`` to turn human-readable names into row ids
         before filtering or writing.
      3. ``list_rows`` (optionally ``include_inlines``) to scan, then
         ``fetch_detail`` to read one object in full.
      4. ``update_detail`` / ``create_object`` to write. For new
         objects call ``fetch_add_form`` first for the field shape.

    Validation failures come back as ``{"status": "invalid",
    "errors": ...}`` with no DB change; permission denials raise
    ``PermissionError``; invisible objects raise ``LookupError``.
    """

    def get_dashboard_blueprint(self) -> dict[str, str]:
        """Return a ready-to-use HTML blueprint for a custom live dashboard.

        Use this when asked to build a local/custom dashboard, report, or UI
        on top of this admin's data. The blueprint is a single static HTML
        file — minimal HTML/CSS, a complete OAuth 2.1 (authorization code +
        PKCE) login against *this* server, and one ``api(tool, args)`` helper
        that calls these MCP tools over JSON-RPC. ``content`` comes back with
        this server's URL already filled in; the agent saves it, fills the
        client_id + scope, and adds cards.

        Returns ``{"filename", "content", "instructions"}`` — follow
        ``instructions`` to scaffold the dashboard.
        """
        from importlib.resources import files

        from django.conf import settings

        content = (
            files("django_smartbase_admin.mcp") / "dashboard_blueprint.html"
        ).read_text(encoding="utf-8")

        # Bake this server's URL into the blueprint so the file is ready to
        # serve without the agent having to know the host.
        base = self.request.build_absolute_uri("/").rstrip("/")
        # Keep the endpoint's trailing slash ("mcp/") — POST /mcp (no slash)
        # doesn't match the route and isn't APPEND_SLASH-redirected.
        mcp_path = getattr(settings, "DJANGO_MCP_ENDPOINT", "mcp/").lstrip("/")
        oauth = getattr(settings, "OAUTH2_PROVIDER", {}) or {}
        scope = " ".join(
            oauth.get("DEFAULT_SCOPES") or list((oauth.get("SCOPES") or {}).keys())
        )
        content = (
            content.replace("__MCP_ISSUER__", base)
            .replace("__MCP_URL__", f"{base}/{mcp_path}")
            .replace("__MCP_SCOPE__", scope)
        )

        instructions = (
            "Build a custom dashboard on this admin's live data. The "
            "returned 'content' is a static HTML page (minimal HTML/CSS, OAuth "
            "PKCE login, and an api(tool, args) helper); it has no backend — "
            "OAuth and every data call go straight from the browser to this "
            "server, and it must be served over http (a file:// page is Origin "
            "'null' and is always CORS-blocked).\n\n"
            "STEPS:\n"
            "  1. Save 'content' as an .html file — this server's URL is already "
            "filled into CONFIG.\n"
            "  2. Register an OAuth client ONCE (redirect_uris = where you serve "
            "the page) via POST <issuer>/oauth/register, then put the returned "
            "client_id into CONFIG. The client_id is a public PKCE client id (no "
            "secret) — safe to hardcode and reused by all users; generate it once "
            "per deployment, not per session. CONFIG.scope is already prefilled "
            "with the scope this server exposes.\n"
            "  3. Serve it over http and open the http URL; click Connect to log "
            "in.\n"
            "  4. Add cards: each calls one MCP tool and renders the result. "
            "Inspect the available tools and their inputs/outputs from this MCP "
            "server (start with list_admins for views, fields and filters).\n\n"
            "SERVER PREREQUISITES — only when the page is NOT served same-origin "
            "behind the admin's gateway: install "
            "'django_smartbase_admin.mcp.middleware.SBAdminMCPCorsMiddleware' in "
            "MIDDLEWARE (early, before auth; off by default), and add the page's "
            "exact origin to SBADMIN_MCP_ALLOWED_ORIGINS (default allows only "
            "claude.ai/cursor.com)."
        )
        return {
            "filename": "custom_dashboard.html",
            "content": content,
            "instructions": instructions,
        }

    @_guarded_tool_call
    def list_admins(self) -> dict[str, list[dict] | dict[str, dict] | dict[str, str]]:
        """List the admins the current user can view.

        Use this to discover the handles every other tool accepts —
        ``view_id``, field/filter names, ``widget_id``s, inline names,
        and ``action_id``s.

        Returns ``{"admin_views": [...], "widget_shapes": {...}}``.
        ``widget_shapes`` is a legend keyed by widget category (the
        ``widget`` value on every filter entry); each value is
        ``{"value_shape": str, "example": <example value>}`` describing
        the expected ``filter_data`` value shape. Subclassed widgets
        (e.g. ``FromValuesAutocompleteWidget``) are reported as their
        base category — only the base controls the ``filter_data``
        contract.

        Schema per admin entry:
          - ``view_id``: pass to other tools as ``view_id``.
          - ``app_label``, ``model``: match against ``target_model`` on
            filter widgets.
          - ``verbose_name``, ``verbose_name_plural``: display names.
          - ``fields``: list-view columns. Each is
            ``{"name", "title", "list_visible"}`` plus an optional
            ``"filter"`` block — present when the column is filterable.
            The filter block carries the widget kind plus any extras
            needed to build a ``filter_data`` value (``"choices"`` for
            choice widgets, ``"multiselect"`` and ``"target_model"``
            for autocomplete widgets).
          - ``search_fields``: columns the ``full_text_search`` arg on
            ``list_rows`` matches against. Empty list means free-text
            search is a no-op on this admin.
          - ``detail_fields``: detail-page field names, in display
            order. Pass to ``fetch_detail(fields=...)`` to project a
            subset; per-field metadata ships with the values.
          - ``inlines``: related rows reachable from the detail page.
            Each entry: ``inline_name`` (key for
            ``fetch_detail.inlines`` and
            ``list_rows(include_inlines=...)``), ``view_id`` (pass to
            ``invoke_inline_action`` when invoking inline actions),
            ``model`` (``"<app>.<Model>"``), ``verbose_name`` /
            ``verbose_name_plural``, ``fields``, ``inline_actions``, and
            ``relations`` — a ``{field: "<app>.<Model>"}`` map for the
            inline's FK / M2M columns. ``include_inlines`` returns those
            columns as bare pks (e.g. ``{"work": 443}``); ``relations``
            names the target model so the agent can interpret the id and
            pick the model to ``autocomplete`` against. (``fetch_detail``
            instead resolves inline FKs to ``{"value", "label"}``
            directly, the same as parent FKs.)

          Action lists — every entry is
          ``{"title", "kind", "action_id",
          "requires_confirmation"?}``. ``kind`` is ``"method"`` (calls
          a server-side method) or ``"modal"`` (opens a form — fetch
          the schema with ``fetch_action_form`` first). The MCP tool to
          call is looked up in the top-level ``action_invokers`` legend
          by action-list name (``row_actions`` →
          ``invoke_row_action``, etc.). ``requires_confirmation: true``
          means the first invoke returns ``needs_confirmation``; pass
          ``confirmed=True`` on the second call to commit. Sub-actions
          (visual dropdown groups in the UI) are flattened to siblings.

          - ``row_actions``: per-row buttons on the list view.
          - ``detail_actions``: buttons on the change / detail form.
          - ``list_actions``: global buttons above the list, no row
            context (e.g. "Create…" modals, exports).
          - ``selection_actions``: bulk buttons over selected rows.
        """
        request = self.request
        ensure_sbadmin_request_data(request)

        admins: list[dict] = []
        for admin in sb_admin_site._registry.values():
            if not isinstance(admin, SBAdminBaseListView):
                continue
            try:
                if not admin.has_view_permission(request):
                    continue
            except Exception:
                continue  # one broken admin shouldn't break discovery
            admins.append(admin_entry(admin, request))

        admins.sort(key=lambda entry: entry["view_id"])
        # ``widget_shapes`` is the legend keyed by the ``widget`` field
        # reported on every filter entry. Emitting it once at the top
        # level keeps each per-field filter block to ``filter_field`` +
        # ``widget`` (+ choices/autocomplete extras) instead of repeating
        # ``value_shape`` / ``example`` for every column.
        # ``action_invokers`` is a sibling legend to ``widget_shapes`` —
        # keyed by action-list name, value is the MCP tool to call.
        # Saves repeating ``invoke_with`` on every individual action.
        return {
            "admin_views": admins,
            "widget_shapes": get_widget_shapes(),
            "action_invokers": ACTION_INVOKERS,
        }

    @_guarded_tool_call
    def fetch_filter_preset(
        self,
        view_id: str,
        name: str | None = None,
        source: str = "static",
        id: int | None = None,
    ) -> dict:
        """Resolve a filter preset (static or saved) into ready-to-use
        ``list_rows`` kwargs.

        ``list_admins`` advertises presets per admin as
        ``{"name", "source", "id"?}`` under ``filter_presets``; pass
        those values straight here. Returns the decoded preset:
        ``filter_data``, ``full_text_search``, ``sort``, ``page_size``
        (only keys the preset actually sets). The agent can splat the
        result onto ``list_rows`` to replay the preset, or merge it with
        overrides. ``page`` is intentionally not returned — a saved page
        number is session state, not part of the preset, so replay
        always starts on page 1.

        Args:
          view_id: admin handle from ``list_admins[].view_id``.
          source: ``"static"`` (admin-defined preset, including the
            implicit ``"All"`` reset) or ``"saved"`` (per-user). Defaults
            to ``"static"`` because saved presets always have an ``id``
            and agents typically discover those first.
          name: preset name as it appears in
            ``list_admins[].filter_presets[].name``. Required for static
            presets; for saved presets, used as a fallback when ``id`` is
            omitted (the name is user-editable so prefer ``id``).
          id: saved preset primary key from
            ``list_admins[].filter_presets[].id``. Ignored for static
            presets.

        Raises ``LookupError`` when no preset matches, ``PermissionError``
        if the user can't see the admin, ``ValueError`` for bad input.
        """
        from django_smartbase_admin.services.configuration import (
            SBAdminUserConfigurationService,
        )

        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)

        field_map = admin.get_field_map(request)

        def decode(url_params):
            decoded = _decode_preset_url_params(url_params)
            # Hand back column ``name`` keys, the single identifier the agent
            # uses everywhere else (list_rows still accepts these on replay).
            if "filter_data" in decoded:
                decoded["filter_data"] = _filter_keys_to_names(
                    decoded["filter_data"], field_map
                )
            return decoded

        if source == "static":
            if not name:
                raise ValueError("'name' is required when source='static'")
            # Decode the *raw* config (clean url_params), not
            # ``get_base_config`` whose output is processed into the
            # URL-ready, JSON-stringified form ``list_rows`` can't take.
            # This mirrors ``get_base_config``'s own assembly: the
            # implicit "All" reset first, then ``sbadmin_list_view_config``.
            raw_presets = [
                admin.get_all_config(request),
                *(admin.get_sbadmin_list_view_config(request) or []),
            ]
            for preset in raw_presets:
                if str(preset.get("name", "")) == name:
                    return decode(preset.get("url_params"))
            raise LookupError(
                f"No static filter preset named {name!r} on {view_id!r}. "
                f"Known: {[str(p.get('name', '')) for p in raw_presets]}"
            )
        if source == "saved":
            saved = (
                SBAdminUserConfigurationService.get_saved_views(
                    request, view_id=view_id
                )
                or []
            )
            for preset in saved:
                # ``id`` is the stable handle; ``name`` is a fallback for
                # callers that don't have the id cached.
                if id is not None and preset.get("id") == id:
                    return decode(preset.get("url_params"))
                if id is None and name and str(preset.get("name", "")) == name:
                    return decode(preset.get("url_params"))
            raise LookupError(
                f"No saved filter preset matching id={id!r} name={name!r} "
                f"on {view_id!r}"
            )
        raise ValueError(f"source must be 'static' or 'saved', got {source!r}")

    @_guarded_tool_call
    def list_rows(
        self,
        view_id: str,
        fields: list[str],
        filter_data: dict | None = None,
        page: int = 1,
        page_size: int = 20,
        sort: list | None = None,
        full_text_search: str | None = None,
        include_inlines: list | None = None,
        aggregate: list | None = None,
    ) -> dict:
        """List rows for one admin — same data the UI list shows.

        Note: ``fields`` is required (non-empty list of column names from
        ``list_admins``). Autocomplete filters need ``[{"value", "label"}, ...]``.

        Permissions, row isolation, filters, ordering, and column
        formatting all match what the user would see browsing the
        admin's list page. Cells come back as plain values, not HTML.

        Args:
          view_id: handle from ``list_admins``.
          fields: non-empty list of column names to return, drawn from
            ``list_admins["admin_views"][].fields[].name``. Every row also
            carries a normalized ``"id"`` key for row identity, regardless
            of the model's pk field name (so ``row["id"]`` is always safe).
          filter_data: ``{field: value}`` mapping. Each **key** is a column
            ``name`` from ``list_admins["admin_views"][].fields[].name`` —
            the same identifier ``fields`` and ``sort`` use. (Keys returned
            by ``fetch_filter_preset`` are also accepted as-is, so a preset
            replays unchanged.) Per filter, read the widget category from
            ``list_admins["admin_views"][].fields[].filter.widget`` and
            copy its ``value_shape`` / ``example`` from
            ``list_admins["widget_shapes"]`` literally — that legend is
            the single source of truth for the per-widget value shape. For
            an autocomplete (related-record) filter, resolve the name to an
            id with the ``autocomplete`` tool first; pass that id as the
            entry ``value`` (a free-text name/email is not a valid id).
            Unknown keys are rejected — misspellings raise instead of
            silently returning every row.
          page: 1-indexed page number (default 1).
          page_size: rows per page (default 20). No enforced maximum —
            set it high to pull the whole filtered set in one call (use
            ``last_row`` from a first probe to size it). Mind context cost
            on large sets.
          sort: list of ``{"field": <name>, "dir": "asc"|"desc"}``
            entries, applied in order. ``field`` is a column name from
            ``list_admins["admin_views"][].fields[].name``; unknown
            fields are rejected with the list of sortable names.
          full_text_search: cross-column free text term — no-op on
            admins whose ``search_fields`` is empty.
          include_inlines: optional list of inline specs to hydrate
            beside each parent row. Each item:
            ``{"inline_name": "...", "fields": [...]}`` where
            ``inline_name`` and ``fields`` are taken from
            ``list_admins["admin_views"][].inlines``.

            Hydrated rows arrive at
            ``row["_inlines"][<inline_name>]``, each with a normalized
            ``"id"`` key. Inline FK / M2M columns come back as bare pks
            (e.g. ``{"work": 443}``); map each to its target model via
            the inline's ``relations`` entry in ``list_admins`` and
            resolve names with ``autocomplete`` (or read one parent in
            full via ``fetch_detail``, which labels inline FKs as
            ``{"value", "label"}``). When a parent has more related rows
            than the inline's pagination cap, the response includes that
            inline name in ``row["_truncated_inlines"]`` and only the
            first page is attached.

          aggregate: optional list of ``{"fn", "field"}`` specs, each a
            total over the WHOLE filtered set (independent of paging).
            ``fn`` is one of ``sum / avg / min / max / count``; ``field``
            must be a declared column from ``list_admins`` —
            ``sum/avg/min/max`` need a numeric one, ``count`` may omit
            ``field`` for a row count. Results land under ``aggregates``,
            keyed ``f"{fn}_{field}"`` (or ``"count"``).

        Returns ``{"data": [...], "last_page": int, "last_row": int}``
        plus any pagination metadata the list view emits, and ``aggregates``
        when the ``aggregate`` argument is supplied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        # Built once and shared — ``get_field_map`` rebuilds + clones on
        # every call.
        field_map = admin.get_field_map(request)
        filter_data = _normalize_filter_keys(filter_data, field_map)
        _validate_filter_data(admin, request, filter_data, field_map)
        _validate_sort(admin, request, sort, field_map)
        columns_data = build_columns_data(admin, request, fields, field_map)

        table_params: dict = {
            TABLE_PARAMS_PAGE_NAME: int(page),
            TABLE_PARAMS_SIZE_NAME: int(page_size),
        }
        if sort:
            table_params[TABLE_PARAMS_SORT_NAME] = sort

        # ``full_text_search`` belongs under ``filterData`` (the list action
        # reads it from ``self.filter_data``), not ``tableParams``.
        filter_payload = dict(filter_data or {})
        if full_text_search:
            filter_payload[TABLE_PARAMS_FULL_TEXT_SEARCH] = full_text_search

        params_payload = {
            view_id: {
                COLUMNS_DATA_NAME: columns_data,
                FILTER_DATA_NAME: filter_payload,
                TABLE_PARAMS_NAME: table_params,
            }
        }
        set_request_payload(
            request,
            get={
                BASE_PARAMS_NAME: SBAdminViewService.json_dumps_for_url(params_payload)
            },
            method="GET",
        )

        # Totals over the whole filtered set, validated before the page fetch.
        aggregates = None
        if aggregate is not None:
            action = admin.sbadmin_list_action_class(admin, request)
            aggregates = action.get_aggregates(aggregate, field_map=field_map)

        # Route through the same action dispatch as the browser so
        # ``has_permission_for_action`` stays the single gate, then unwrap
        # the JSON and drop UI-only payload (notifications, per-row action
        # buttons advertised once via ``list_admins["admin_views"][].row_actions``, HTML
        # markup in cell values).
        response = SBAdminViewService.delegate_to_action(
            request,
            view=admin.get_id(),
            action=Action.LIST_JSON.value,
            modifier="template",
        )
        result = json.loads(response.content.decode())
        result.pop(SB_ADMIN_AJAX_NOTIFICATIONS_KEY, None)
        rows = result.get("data") or []
        # Mirror the pk to a stable ``"id"`` key (the list action keys it
        # under the model's pk name, e.g. ``"emergency_uuid"``).
        pk_attname = admin.model._meta.pk.attname
        for row in rows:
            row.pop("_row_actions", None)
            if pk_attname != "id" and "id" not in row and pk_attname in row:
                row["id"] = row[pk_attname]
        strip_html_cells(admin, request, rows)
        if include_inlines:
            attach_inlines(admin, request, rows, include_inlines)
        if aggregates is not None:
            result["aggregates"] = aggregates
        return result

    @_guarded_tool_call
    def fetch_detail(
        self,
        view_id: str,
        object_id: str,
        fields: list[str] | None = None,
    ) -> dict:
        """Fetch detail-page data for one object.

        Permissions and row isolation match the UI detail page (an
        object the user wouldn't see there is reported missing). All
        inlines the user can view are always hydrated.

        Display fields that render HTML in the UI are sanitized for the
        agent: structural markup (tables, lists, links, ``div`` / ``span``)
        is kept, but styling, classes, and ``<script>`` / ``<style>`` are
        stripped. Inline FK / M2M values are resolved to
        ``{"value", "label"}`` here (unlike ``list_rows(include_inlines)``,
        which returns bare pks).

        Args:
          view_id: handle from ``list_admins``.
          object_id: target row id (as a string).
          fields: optional subset of ``list_admins["admin_views"][].detail_fields``.
            ``None`` returns every detail field; unknown names raise
            ``LookupError``. Inline rows always come back with every
            field the inline declares.

        Returns ``{"id": <id>, "fields": {<name>: <info>, ...},
        "inlines": {<inline_name>: {"rows": [...], "truncated":
        <bool>}, ...}}`` where ``<info>`` is ``{"value", "readonly",
        "required", "widget"}``:

        * ``value`` — scalar, or ``{"value": <id>, "label": <display>}``
          (list of those for multi-select) for related selections.
        * ``readonly`` — ``True`` for static fields.
        * ``required`` — would the form reject a blank submission.
          Always ``False`` for readonly fields.
        * ``widget`` — opaque input-family hint
          (text / select / date / ...), ``None`` when readonly.
        * ``widget_id`` — present on autocomplete-backed fields; pass to
          ``autocomplete`` (never construct by hand).

        Each ``inlines[<name>].rows`` entry mirrors the parent
        ``{"id", "fields"}`` shape. ``truncated`` is ``True`` when a
        paginated inline has more rows than carried here — drill in
        via ``list_rows`` on the inline's own admin.

        Raises ``LookupError`` if the object isn't visible,
        ``PermissionError`` if permission is denied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.get_detail_data(
                admin, request, object_id, fields=fields
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_guarded_tool_call
    def fetch_add_form(
        self,
        view_id: str,
        fields: list[str] | None = None,
    ) -> dict:
        """Fetch the add page's empty form — schema for ``create_object``.

        Note: inline ``rows`` are empty on add; resolve FK ids via ``autocomplete``
        (often from another admin's filter with the same ``filter.target_model``).

        Mirrors :meth:`fetch_detail` without ``id``: same ``fields`` /
        ``inlines`` shape, same ``{"value", "readonly", "required",
        "widget"[, "widget_id"]}`` per field. ``value`` carries the
        form's default for that field. Inline ``rows`` come back
        empty (no persisted rows exist yet).

        Use before ``create_object`` to discover ``widget_id`` for
        autocomplete-backed fields (needed for the ``autocomplete``
        tool) and to inspect which fields are required.

        Raises ``PermissionError`` if add permission is denied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.get_add_form_data(
                admin, request, fields=fields
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_guarded_tool_call
    def fetch_action_form(
        self,
        view_id: str,
        action_id: str,
        object_id: str | None = None,
    ) -> dict:
        """Fetch the form schema for a modal action — prerequisite for invoking it.

        Works for any action with ``kind == "modal"`` in ``list_admins``.
        ``action_id`` always comes from discovery.

        Pass ``object_id`` when the action is row- or detail-scoped so
        the form is pre-populated with that row's current values. Omit
        for list-level / selection modals that have no single-row context.

        Returns ``{"title": "…", "fields": {<name>: <info>, …}}`` where
        each ``<info>`` is:

          - ``label``        — human-readable field label.
          - ``value``        — initial / default value, or ``None``.
          - ``required``     — whether a blank submission is rejected.
          - ``widget``       — widget class name hint.
          - ``target_model`` — present on relational fields
            (``"<app>.<Model>"``); use with ``autocomplete`` to resolve
            a name to a pk before submitting.
          - ``widget_id``    — present on autocomplete-backed widgets;
            pass directly to the ``autocomplete`` tool.
          - ``choices``      — present on flat-choice fields; list of
            ``{"value": …, "label": …}``.

        Raises ``LookupError`` if ``action_id`` is not a known modal
        action on ``view_id``, or if ``object_id`` is required but not
        visible. Raises ``PermissionError`` if access is denied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPActionFormService.get_action_form_data(
                admin, request, action_id, object_id=object_id
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_guarded_tool_call
    def create_object(
        self,
        view_id: str,
        field_values: dict | None = None,
        inlines: dict | None = None,
    ) -> dict:
        """Create one object — symmetric with ``update_detail``.

        Note: ``inlines`` keys are ``inline_name`` values from ``list_admins``
        (inline class names). New inline rows must not include ``id`` or ``_delete``.

        Same permission model and POST pipeline as the UI add page.
        ``field_values`` supplies the parent row; ``inlines`` adds
        related rows (creates only — ``id`` / ``_delete`` are rejected
        because there's nothing to update yet).

        Call ``fetch_add_form`` first to discover the field shape and
        ``widget_id`` values for autocomplete-backed fields.

        Args:
          view_id: handle from ``list_admins``.
          field_values: ``{name: value}`` for the parent form. Accepts
            either raw scalars/pks or the ``{"value", "label"}``
            envelope ``fetch_detail`` returns. Unknown or readonly names
            raise ``LookupError``; unspecified writable fields fall back
            to the form's documented default.
          inlines: ``{inline_name: [{...field values}, ...]}`` keyed by
            the ``inline_name`` used by ``fetch_detail`` /
            ``fetch_add_form``. Inlines not mentioned start empty.
            Unknown inline names raise ``LookupError``.

        Returns ``{"status": "ok", "id": <new_pk>, "fields": ...,
        "inlines": ...}`` mirroring ``fetch_detail`` after the save, or
        ``{"status": "invalid", "errors": {"fields": {...}, "inlines":
        {<inline_name>: {"rows": [...], "non_form": [...]}, ...}}}``
        when validation fails (no DB write happens — the agent can
        retry with corrected values).

        Raises ``PermissionError`` if add permission is denied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.create_object_data(
                admin,
                request,
                field_values=field_values,
                inlines=inlines,
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_guarded_tool_call
    def update_detail(
        self,
        view_id: str,
        object_id: str,
        field_values: dict | None = None,
        inlines: dict | None = None,
    ) -> dict:
        """Write detail-page data for one object — symmetric with ``fetch_detail``.

        Same permission gates and row isolation as the UI change form,
        and the same form/inline shape as ``fetch_detail`` returns —
        unspecified fields keep their current values.

        Args:
          view_id: handle from ``list_admins``.
          object_id: target row id (as a string).
          field_values: ``{name: value}`` for the parent row. Values
            accept either raw scalars/pks or the ``{"value", "label"}``
            envelope ``fetch_detail`` returns, so an agent can echo a
            fetched payload back. Unknown or readonly names raise
            ``LookupError``.
          inlines: ``{inline_name: [row_op, ...]}`` keyed by the same
            ``inline_name`` used by ``fetch_detail``. Each op is:

            * ``{"id": <pk>, ...overrides}`` — update an existing row.
            * ``{"id": <pk>, "_delete": true}`` — delete the row.
            * ``{...field values}`` (no ``id``) — create a new row.

            Inlines not mentioned are passed through unchanged. Unknown
            inline names or row ids raise ``LookupError``.

        Returns ``{"status": "ok", "id": ..., "fields": ...,
        "inlines": ...}`` mirroring ``fetch_detail`` after the save, or
        ``{"status": "invalid", "errors": {"fields": {...}, "inlines":
        {<inline_name>: {"rows": [...], "non_form": [...]}, ...}}}``
        when validation fails (no DB write happens — the agent can
        retry with corrected values).

        Raises ``LookupError`` if the object isn't visible,
        ``PermissionError`` if change permission is denied.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.update_detail_data(
                admin,
                request,
                object_id,
                field_values=field_values,
                inlines=inlines,
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_guarded_tool_call
    def get_audit_history(
        self,
        view_id: str,
        object_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Audit log entries for an admin's model, paginated newest-first.

        Same data the "History" button on the list / detail page would
        show. Pass ``object_id`` to scope to one object's history; omit
        for everything on the model. Only available when the admin has
        ``sbadmin_list_history_enabled`` (the default) and the audit app
        is installed.

        Args:
          view_id: handle from ``list_admins``.
          object_id: optional row id; ``None`` returns all entries for
            the model.
          page: 1-indexed page number (default 1).
          page_size: rows per page (default 20). No enforced maximum —
            set it high to pull the full history in one call (use
            ``last_row`` to size it).

        Returns ``{"data": [<entry>, ...], "page": int, "page_size": int,
        "last_row": int}`` where each ``<entry>`` is ``{"id", "timestamp",
        "action_type", "user", "object_id", "object_repr", "is_bulk",
        "bulk_count", "changes", "source"}``.

        Raises ``LookupError`` if history is disabled on this admin or
        the audit app isn't installed.
        """
        from django.apps import apps as django_apps

        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        if not getattr(admin, "sbadmin_list_history_enabled", False):
            raise LookupError(f"Audit history is disabled on view_id={view_id!r}.")
        if not django_apps.is_installed("django_smartbase_admin.audit"):
            raise LookupError(
                "Audit app (`django_smartbase_admin.audit`) is not installed."
            )

        admin.init_view_dynamic(request, request.request_data)
        from django_smartbase_admin.audit.mcp import get_admin_history

        return get_admin_history(
            admin,
            request=request,
            object_id=object_id,
            page=page,
            page_size=page_size,
        )

    @_guarded_tool_call
    def delete_objects(
        self,
        view_id: str,
        object_ids: list,
        confirmed: bool = False,
    ) -> dict:
        """Delete one or more objects on an admin.

        Real deletes — destructive and irrecoverable.

        Two-step contract:
          1. First call (``confirmed=False``) returns
             ``{"status": "needs_confirmation", "message": "...",
             "data": {"count": N, "sample": [...], "cascade": {...}}}``.
             ``cascade`` lists every related model that will be deleted
             alongside the target.
          2. Second call with ``confirmed=True`` performs the delete.

        Prerequisites:
          1. Call ``list_rows`` with the filter that identifies your
             candidates and verify the ids.
          2. Confirm the affected ids + count with the user before
             passing ``confirmed=True``.

        Args:
          view_id: handle from ``list_admins``.
          object_ids: non-empty list of row ids (as strings).
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}`` after delete,
        ``{"status": "needs_confirmation", ...}`` on the first call, or
        ``{"status": "invalid", "errors": {"non_field": [...]}}`` if a
        protected ForeignKey blocks the delete.

        Raises ``ValueError`` if ``object_ids`` is empty,
        ``PermissionError`` if delete permission is missing.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        return SBAdminMCPActionInvokeService.delete_objects(
            admin,
            request,
            object_ids=object_ids,
            confirmed=confirmed,
        )

    @_guarded_tool_call
    def invoke_row_action(
        self,
        view_id: str,
        action_id: str,
        object_id: str,
        field_values: dict | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Invoke a row action against one object.

        Side effects match clicking the action in the UI — writes,
        deletes, and external API calls are real and irrecoverable.

        Prerequisites:
          1. Resolve the target via ``fetch_detail`` or ``list_rows``.
          2. For ``kind == "modal"``: call ``fetch_action_form(view_id,
             action_id, object_id)`` for the form schema, then use
             ``autocomplete`` for any ``target_model`` FK fields.

        Args:
          view_id: admin handle from ``list_admins``.
          action_id: ``action_id`` from ``list_admins["admin_views"][].row_actions``.
          object_id: target row id (as a string).
          field_values: form submission for ``kind == "modal"``; absent
            for ``kind == "method"``. Accepts raw scalars/pks or the
            ``{"value", "label"}`` envelope.
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}``,
        ``{"status": "invalid", "errors": {...}}``, or
        ``{"status": "needs_confirmation", "message": "...", "data": {...}}``.
        Cross-field / view-raised errors under ``"non_field"``.

        Raises ``PermissionError`` if access is denied, ``LookupError``
        if the action / object isn't visible, ``ValueError`` if
        ``field_values`` is supplied for a method action.
        """
        return self._invoke_per_object(
            view_id,
            action_id,
            object_id,
            field_values,
            confirmed,
        )

    @_guarded_tool_call
    def invoke_detail_action(
        self,
        view_id: str,
        action_id: str,
        object_id: str,
        field_values: dict | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Invoke a detail-page action against one object.

        Side effects match clicking the action in the UI — writes,
        deletes, and external API calls are real and irrecoverable.

        Prerequisites:
          1. Resolve the target via ``fetch_detail`` or ``list_rows``.
          2. For ``kind == "modal"``: call ``fetch_action_form(view_id,
             action_id, object_id)`` for the form schema, then use
             ``autocomplete`` for any ``target_model`` FK fields.

        Args:
          view_id: admin handle from ``list_admins``.
          action_id: ``action_id`` from ``list_admins["admin_views"][].detail_actions``.
          object_id: target row id (as a string).
          field_values: form submission for ``kind == "modal"``; absent
            for ``kind == "method"``. Accepts raw scalars/pks or the
            ``{"value", "label"}`` envelope.
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}``,
        ``{"status": "invalid", "errors": {...}}``, or
        ``{"status": "needs_confirmation", "message": "...", "data": {...}}``.
        Cross-field / view-raised errors under ``"non_field"``.

        Raises ``PermissionError`` if access is denied, ``LookupError``
        if the action / object isn't visible, ``ValueError`` if
        ``field_values`` is supplied for a method action.
        """
        return self._invoke_per_object(
            view_id,
            action_id,
            object_id,
            field_values,
            confirmed,
        )

    @_guarded_tool_call
    def invoke_inline_action(
        self,
        view_id: str,
        action_id: str,
        object_id: str,
        field_values: dict | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Invoke an inline-list action against one inline row.

        Side effects match clicking the action in the UI — writes,
        deletes, and external API calls are real and irrecoverable.

        Prerequisites:
          1. Resolve the target via ``list_rows(include_inlines=...)``
             so you have the inline row's pk and current state.
          2. For ``kind == "modal"``: call ``fetch_action_form(view_id,
             action_id, object_id)`` for the form schema, then use
             ``autocomplete`` for any ``target_model`` FK fields.

        Args:
          view_id: inline's ``view_id`` from
            ``list_admins[<parent>].inlines[].view_id`` (not the parent's).
          action_id: ``action_id`` from
            ``list_admins[<parent>].inlines[].inline_actions``.
          object_id: inline row pk (as a string).
          field_values: form submission for ``kind == "modal"``; absent
            for ``kind == "method"``. Accepts raw scalars/pks or the
            ``{"value", "label"}`` envelope.
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}``,
        ``{"status": "invalid", "errors": {...}}``, or
        ``{"status": "needs_confirmation", "message": "...", "data": {...}}``.
        Cross-field / view-raised errors under ``"non_field"``.

        Raises ``PermissionError`` if access is denied, ``LookupError``
        if the action / object isn't visible, ``ValueError`` if
        ``field_values`` is supplied for a method action.
        """
        return self._invoke_per_object(
            view_id,
            action_id,
            object_id,
            field_values,
            confirmed,
        )

    def _invoke_per_object(
        self,
        view_id,
        action_id,
        object_id,
        field_values,
        confirmed,
    ):
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        return SBAdminMCPActionInvokeService.invoke_row(
            admin,
            request,
            action_id=action_id,
            object_id=object_id,
            field_values=field_values,
            confirmed=confirmed,
        )

    @_guarded_tool_call
    def invoke_selection_action(
        self,
        view_id: str,
        action_id: str,
        object_ids: list,
        field_values: dict | None = None,
        confirmed: bool = False,
        modifier: str | None = None,
    ) -> dict:
        """Invoke a selection (bulk) action over an explicit id list.

        Side effects match clicking the action in the UI on a selected
        set of rows — writes, deletes, and external API calls are real
        and irrecoverable.

        Prerequisites you must satisfy before calling:
          1. Call ``list_rows`` (with the ``filter_data`` /
             ``full_text_search`` that identifies your candidates) and
             verify exactly which rows you intend to act on.
          2. For destructive actions (delete, archive, etc.), confirm
             the affected ids and count with the user.
          3. For ``kind == "modal"``: call ``fetch_action_form(view_id,
             action_id)`` for the form shape.

        ``object_ids`` is the explicit, canonical selection. Empty lists
        are rejected so accidental "operate on everything" is impossible.

        Args:
          view_id: handle from ``list_admins``.
          action_id: ``action_id`` from
            ``list_admins["admin_views"][].selection_actions``.
          object_ids: non-empty list of row ids (as strings).
          field_values: form submission for ``kind == "modal"``; absent
            for ``kind == "method"``.
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}`` on success
        (``messages`` typically carries the affected-row count from the
        view), ``{"status": "invalid", "errors": {...}}`` on modal
        validation failure, or ``{"status": "needs_confirmation",
        "message": "...", "data": {...}}`` when the action wants explicit
        confirmation. Cross-field / view-raised errors appear under the
        key ``"non_field"``.

        Raises ``ValueError`` if ``object_ids`` is empty,
        ``PermissionError`` if access is denied.
        """

        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        return SBAdminMCPActionInvokeService.invoke_selection(
            admin,
            request,
            action_id=action_id,
            object_ids=object_ids,
            field_values=field_values,
            confirmed=confirmed,
            modifier=modifier,
        )

    @_guarded_tool_call
    def invoke_list_action(
        self,
        view_id: str,
        action_id: str,
        field_values: dict | None = None,
        filter_data: dict | None = None,
        full_text_search: str | None = None,
        confirmed: bool = False,
        modifier: str | None = None,
    ) -> dict:
        """Invoke a list-level action (no row context).

        Side effects match clicking the action in the UI — creates,
        exports, and external API calls are real.

        Prerequisites you must satisfy before calling:
          1. If ``filter_data`` / ``full_text_search`` is supplied, call
             ``list_rows`` with the same filter to confirm the scope.
          2. For ``kind == "modal"`` (e.g. "Create …"): call
             ``fetch_action_form(view_id, action_id)`` for the form
             shape, then use ``autocomplete`` for any ``target_model``
             FK fields.

        Args:
          view_id: handle from ``list_admins``.
          action_id: ``action_id`` from
            ``list_admins["admin_views"][].list_actions``.
          field_values: form submission for ``kind == "modal"``; absent
            for ``kind == "method"``.
          filter_data, full_text_search: optional scope, same shapes as
            ``list_rows`` — only used by filter-aware actions.
          confirmed: set to ``True`` on the second call after a
            ``needs_confirmation`` response.

        Returns ``{"status": "ok", "messages": [...]}`` on success,
        ``{"status": "invalid", "errors": {...}}`` on modal validation
        failure, or ``{"status": "needs_confirmation", "message": "...",
        "data": {...}}`` when the action wants explicit confirmation.
        Cross-field / view-raised errors appear under the key
        ``"non_field"``.

        Raises ``PermissionError`` if access is denied.
        """

        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)
        # Callers pass column-name keys (per the schema/presets), so re-key to
        # the ``filter_field`` the list pipeline uses — same as ``list_rows``,
        # otherwise a filter-aware action gets the wrong/unknown filter keys.
        field_map = admin.get_field_map(request)
        filter_data = _normalize_filter_keys(filter_data, field_map)
        _validate_filter_data(admin, request, filter_data, field_map)
        return SBAdminMCPActionInvokeService.invoke_list(
            admin,
            request,
            action_id=action_id,
            field_values=field_values,
            filter_data=filter_data,
            full_text_search=full_text_search,
            confirmed=confirmed,
            modifier=modifier,
        )

    @_guarded_tool_call
    def autocomplete(
        self,
        view_id: str,
        widget_id: str,
        search: str = "",
        page: int = 1,
    ) -> list[dict]:
        """Search an autocomplete-backed field — same dropdown the UI shows.

        Dispatches straight to the admin's ``action_autocomplete`` URL
        action by widget id, so list-filter dropdowns and detail-form
        pickers go through one path. Use this to turn a human-readable
        name into a row id before calling ``list_rows`` (filter) or
        before writing a value (form field).

        Args:
          view_id: handle from ``list_admins``.
          widget_id: opaque widget identifier from
            ``list_admins["admin_views"][].fields[].filter.widget_id`` (list filters)
            or ``fetch_detail`` / ``fetch_add_form`` →
            ``fields.<name>.widget_id`` (parent form; inline FK fields on
            add usually lack ``widget_id`` — use another admin's filter
            with the same ``filter.target_model`` instead).
            Never construct by hand; unauthorised fields omit ``widget_id``.
            Action permission and ``restrict_queryset`` are enforced
            inside ``action_autocomplete`` itself.
          search: free text term — empty string returns the first page
            of all matches.
          page: 1-indexed page number. Pages are 20 entries.

        Returns ``[{"value": ..., "label": ...}, ...]`` ready to drop
        into ``filter_data`` (or into a write call for form fields).
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id, request=request)
        admin.init_view_dynamic(request, request.request_data)

        set_request_payload(
            request,
            post={
                AUTOCOMPLETE_SEARCH_NAME: search,
                AUTOCOMPLETE_PAGE_NUM: str(int(page)),
                AUTOCOMPLETE_FORWARD_NAME: "{}",
            },
            method="POST",
        )

        try:
            response = SBAdminViewService.delegate_to_action(
                request,
                view=admin.get_id(),
                action=Action.AUTOCOMPLETE.value,
                modifier=widget_id,
            )
        except Http404:
            # ``action_autocomplete`` raises a bare (empty-message) Http404
            # for an unknown/hidden widget_id; give a clear error instead.
            raise LookupError(
                f"No autocomplete widget {widget_id!r} on {view_id!r}. Copy "
                "widget_id verbatim from list_admins fields[].filter.widget_id "
                "or fetch_detail / fetch_add_form fields.<name>.widget_id."
            )
        except PermissionDenied as exc:
            # The widget delegates to its target-model admin, which enforces
            # its own ``view`` permission. When the user can't view that
            # target, ``action_autocomplete`` raises a *bare* PermissionDenied
            # (empty message) — the agent then sees only the class name. Keep
            # the type (callers gate on it) but attach a reason it can act on.
            raise PermissionDenied(
                f"Not permitted to use autocomplete widget {widget_id!r} on "
                f"{view_id!r}: its target-model admin is not viewable by your "
                "account."
            ) from exc
        return json.loads(response.content.decode())["data"]
