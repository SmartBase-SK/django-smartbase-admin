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
from mcp_server import MCPToolset

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.const import (
    Action,
    AUTOCOMPLETE_FORWARD_NAME,
    AUTOCOMPLETE_PAGE_NUM,
    AUTOCOMPLETE_SEARCH_NAME,
    BASE_PARAMS_NAME,
    COLUMNS_DATA_NAME,
    FILTER_DATA_NAME,
    SB_ADMIN_AJAX_NOTIFICATIONS_KEY,
    TABLE_PARAMS_FULL_TEXT_SEARCH,
    TABLE_PARAMS_NAME,
    TABLE_PARAMS_PAGE_NAME,
    TABLE_PARAMS_SIZE_NAME,
    TABLE_PARAMS_SORT_NAME,
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
from django_smartbase_admin.mcp.schema import admin_entry
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.views import SBAdminViewService


def _clear_thread_local_after_call(method):
    """Ensure the bridge-bound thread-local request is cleared after every
    tool call. ``ensure_sbadmin_request_data`` binds it for the duration
    of the call so SBAdmin internals (and the audit hook) see the active
    request, but MCP transport never fires ``request_finished`` — without
    this wrapper the binding leaks across calls and tests, causing audit
    rows to be written under stale users.
    """
    from functools import wraps

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            SBAdminThreadLocalService.clear_request()

    return wrapper


class SBAdminTools(MCPToolset):
    """Tools over the SBAdmin admin surface.

    Every tool runs as the authenticated user — same permissions, row
    isolation, filters, and column rules the user would see in the UI.
    Discovery (``list_admins``, ``fetch_add_form``) and reads
    (``list_rows``, ``fetch_detail``, ``autocomplete``) are read-only;
    ``update_detail`` and ``create_object`` write through the same
    change-form pipeline the UI uses.

    Typical agent flow:
      1. ``list_admins`` once per session to discover ``view_id``s,
         field/filter/inline handles, and ``widget_id``s.
      2. ``autocomplete`` to turn human-readable names into row ids
         before filtering or writing.
      3. ``list_rows`` (optionally with ``include_inlines``) to scan,
         then ``fetch_detail`` to read one object in full.
      4. ``update_detail`` to write — echo the ``fetch_detail`` payload
         back with edits, or send a sparse ``field_values`` /
         ``inlines`` patch. For new objects call ``fetch_add_form``
         first to discover the field shape, then ``create_object``.

    Writes go through Django's full validation + save cycle, including
    inline formsets. Validation failures come back as
    ``{"status": "invalid", "errors": ...}`` with no DB change so the
    agent can retry; permission denials raise ``PermissionError`` and
    invisible objects raise ``LookupError`` (matching the UI's "not
    found" branch).
    """

    @_clear_thread_local_after_call
    def list_admins(self) -> list[dict]:
        """List the admins the current user can view.

        Returns one entry per admin the caller has read access to. Use
        this to discover what's available before calling other tools —
        the field, filter, inline, and action handles other tools
        accept come from here.

        Schema per entry:
          - ``admin_name``: admin class name (e.g. ``"ArticleAdmin"``).
          - ``view_id``: handle to pass to other tools as ``view_id``,
            shaped ``"<app_label>_<model_name>"``.
          - ``app_label``, ``model``, ``base_model``, ``is_proxy``:
            identity hints — useful for telling apart proxies that
            point at the same underlying table.
          - ``verbose_name``, ``verbose_name_plural``: display names.
          - ``fields``: list of list-view columns visible to this user.
            Each descriptor is ``{"name", "title", "list_visible"}``
            plus an optional ``"filter"`` block — present when the
            column is filterable. The filter block carries the widget
            kind plus any extras the agent needs to construct a
            ``filter_data`` value (``"choices"`` for choice-style
            widgets, ``"multiselect"`` and ``"target_model"`` for
            autocomplete widgets).
          - ``search_fields``: columns the ``full_text_search`` arg on
            ``list_rows`` matches against. Empty list means free-text
            search has no effect on this admin — filter via
            ``filter_data`` or ``autocomplete`` instead.
          - ``detail_fields``: flat list of field names the detail
            page renders, in display order. Per-field metadata
            (readonly / widget) ships with the values from
            ``fetch_detail``, not here. Use these names with
            ``fetch_detail(fields=...)`` to project a subset.
          - ``inlines``: related-model views reachable through this
            admin. Each entry: ``inline_name`` (handle keying the
            ``inlines`` block on ``fetch_detail`` and the
            ``list_rows(include_inlines=...)`` spec), ``model``
            (``"<app>.<Model>"``), ``verbose_name`` /
            ``verbose_name_plural``, ``join_kind`` (``"fk"`` /
            ``"generic"`` / ``"fake"`` — for the agent's own
            classification, not a wire detail), and ``fields`` (the
            inline's available column names).
          - ``row_actions``: per-row actions declared on the admin.
            Each entry: ``title``, ``kind`` (``"method"`` —
            non-interactive callable; ``"modal"`` — opens a form;
            ``"url"`` — plain link; ``"group"`` — dropdown with
            ``sub_actions``), and a handle (``action_id`` for
            method/modal, ``target_view`` class name for modal).
            Resolved per-row state (URLs, icons, whether the action is
            enabled for that row) is intentionally not returned —
            invoke the action to act, not to inspect.
        """
        request = self.request
        ensure_sbadmin_request_data(request)

        result: list[dict] = []
        for admin in sb_admin_site._registry.values():
            if not isinstance(admin, SBAdminBaseListView):
                continue
            try:
                if not admin.has_view_permission(request):
                    continue
            except Exception:
                continue  # one broken admin shouldn't break discovery
            result.append(admin_entry(admin, request))

        result.sort(key=lambda entry: entry["view_id"])
        return result

    @_clear_thread_local_after_call
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
            ``list_admins[].fields[].name``. The primary key is always
            included for row identity.
          filter_data: ``{filter_field: value}`` mapping. The value
            shape per filter depends on the widget reported by
            ``list_admins``: choice filters take a string, multi /
            autocomplete filters take a list of
            ``{"value": …, "label": …}`` entries, boolean filters take
            a bool, date/string filters take a string.
          page, page_size: pagination, 1-indexed.
          sort: list of ``{"field": <name>, "dir": "asc"|"desc"}``
            entries, applied in order.
          full_text_search: cross-column free text term — no-op on
            admins whose ``search_fields`` is empty.
          include_inlines: optional list of inline specs to hydrate
            beside each parent row. Each item:
            ``{"inline_name": "...", "fields": [...]}`` where
            ``inline_name`` and ``fields`` are taken from
            ``list_admins[].inlines``.

            Hydrated rows arrive at
            ``row["_inlines"][<inline_name>]``. When a parent has more
            related rows than the inline's pagination cap, the
            response includes that inline name in
            ``row["_truncated_inlines"]`` and only the first page is
            attached.

        Returns ``{"data": [...], "last_page": int, "last_row": int}``
        plus any pagination metadata the list view emits.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id)
        admin.init_view_dynamic(request, request.request_data)
        columns_data = build_columns_data(admin, request, fields)

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
            get={BASE_PARAMS_NAME: json.dumps(params_payload)},
            method="GET",
        )

        # Route through the same action dispatch as the browser so
        # ``has_permission_for_action`` stays the single gate, then unwrap
        # the JSON and drop UI-only payload (notifications, per-row action
        # buttons advertised once via ``list_admins[].row_actions``, HTML
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
        for row in rows:
            row.pop("_row_actions", None)
        strip_html_cells(admin, request, rows)
        if include_inlines:
            attach_inlines(admin, request, rows, include_inlines)
        return result

    @_clear_thread_local_after_call
    def fetch_detail(
        self,
        view_id: str,
        object_id: str,
        fields: list[str] | None = None,
    ) -> dict:
        """Fetch detail-page data for one object — values only, no markup.

        Permissions and row isolation match the UI detail page (an
        object the user wouldn't see there is reported missing). All
        inlines the user can view are always hydrated.

        Args:
          view_id: handle from ``list_admins``.
          object_id: target row id (as a string).
          fields: optional subset of ``list_admins[].detail_fields``.
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
        admin = resolve_admin(view_id)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.get_detail_data(
                admin, request, object_id, fields=fields
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_clear_thread_local_after_call
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
        admin = resolve_admin(view_id)
        admin.init_view_dynamic(request, request.request_data)
        try:
            return SBAdminMCPDetailService.get_add_form_data(
                admin, request, fields=fields
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc

    @_clear_thread_local_after_call
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
        admin = resolve_admin(view_id)
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

    @_clear_thread_local_after_call
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
        admin = resolve_admin(view_id)
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

    @_clear_thread_local_after_call
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
            ``list_admins[].fields[].filter.widget_id`` (list filters)
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
        admin = resolve_admin(view_id)
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

        response = SBAdminViewService.delegate_to_action(
            request,
            view=admin.get_id(),
            action=Action.AUTOCOMPLETE.value,
            modifier=widget_id,
        )
        return json.loads(response.content.decode())["data"]
