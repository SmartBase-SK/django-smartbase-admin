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
from django_smartbase_admin.mcp.bridge import (
    build_columns_data,
    ensure_sbadmin_request_data,
    set_request_payload,
    strip_html_cells,
)
from django_smartbase_admin.mcp.inlines import attach_inlines
from django_smartbase_admin.mcp.resolvers import (
    resolve_admin,
    resolve_filter_widget,
)
from django_smartbase_admin.mcp.schema import admin_entry
from django_smartbase_admin.services.views import SBAdminViewService


class SBAdminTools(MCPToolset):
    """Read-only tools over the SBAdmin admin surface.

    Every tool runs as ``self.request.user`` through the full SBAdmin
    pipeline (permissions, ``restrict_queryset``, formatters, plugins).
    """

    def list_admins(self) -> list[dict]:
        """List SBAdmin admins the current user can view.

        Returns one entry per admin the caller has ``view`` permission on.
        Each entry lets an agent disambiguate proxies (``model`` vs
        ``base_model``) and discover which list-view fields are exposed
        for *this* user (since ``get_sbadmin_list_display`` is
        request-aware and may differ by role).

        Schema:
          - ``admin_name``: admin class name (e.g. ``"ArticleAdmin"``)
          - ``view_id``: SBAdmin view id, ``"<app_label>_<model_name>"``
          - ``app_label``, ``model``, ``base_model``, ``is_proxy``
          - ``verbose_name``, ``verbose_name_plural``
          - ``fields``: list of column descriptors visible to this user.
            Each descriptor is ``{"name", "title", "list_visible"}`` plus
            an optional ``"filter": {"filter_field", "widget", ...}``.
            ``filter`` is omitted when the column isn't filterable. For
            choice-style widgets the filter carries ``"choices"``; for
            autocomplete widgets it carries ``"multiselect"`` and (when
            available) ``"target_model"`` as ``"<app>.<Model>"``.
          - ``search_fields``: columns the ``full_text_search`` arg on
            ``list_rows`` matches against. Empty list means free-text
            search is a no-op on this admin — filter via ``filter_data``
            or ``autocomplete`` instead.
          - ``inlines``: related-model inlines the user can view — i.e.
            joins reachable through the admin. Each entry:
            ``inline_name``, ``model`` (``"<app>.<Model>"``),
            ``verbose_name`` / ``verbose_name_plural``,
            ``join_kind`` (``"fk"`` / ``"generic"`` / ``"fake"`` —
            high-level semantics; the underlying ORM keys stay
            server-side), and ``fields`` (declared inline fields).
          - ``row_actions``: per-row actions declared on the admin.
            Each entry carries ``title``, ``kind`` (``"method"`` —
            ``@sbadmin_action`` callable; ``"modal"`` — opens a form
            view; ``"url"`` — plain link), plus a handle: ``action_id``
            for ``method`` / ``modal``, or ``target_view`` (class name)
            for ``modal``. Per-row data (resolved URLs, icons,
            enablement) stays server-side — ``list_rows`` does not
            return it.
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
        """Run an admin's list-view JSON action — same pipeline as the UI table.

        Wraps ``SBAdminListAction.get_json_data()``: every filter,
        column formatter, plugin (``modify_*_queryset`` / ``modify_final_data``),
        and ``restrict_queryset`` runs as the authenticated user.

        Args:
          view_id: ``"<app_label>_<model_name>"`` from ``list_admins``.
          fields: non-empty list of parent row fields to return, using
            ``list_admins[].fields[].name`` handles. The primary key is
            always included for row identity.
          filter_data: ``{filter_field: value}`` mapping. The shape per
            value depends on the widget reported by ``list_admins``:
            ``ChoiceFilterWidget`` takes a string; ``Multiple…`` and
            ``Autocomplete…`` take ``[{"value": …, "label": …}, …]``;
            ``BooleanFilterWidget`` takes a bool; date/string widgets
            take a string.
          page, page_size: pagination, 1-indexed.
          sort: tabulator sort list, e.g.
            ``[{"field": "created_at", "dir": "desc"}]``.
          full_text_search: cross-column free text term.
          include_inlines: optional list of inline specs to hydrate next to
            each parent row. Each item must be
            ``{"inline_name": "...", "fields": [...]}``; inline ``fields``
            must be a non-empty subset of the inline fields advertised by
            ``list_admins``.

            Hydrated rows are attached as ``row["_inlines"][<inline_name>]``.
            Inlines that declare pagination (e.g. ``SBAdminTableInlinePaginated``)
            are capped at ``per_page`` per parent; parents that hit the cap
            are listed in ``row["_truncated_inlines"]``.

        Returns the same payload the browser receives:
        ``{"data": [...], "last_page": int, "last_row": int, ...}``.
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
            get={
                BASE_PARAMS_NAME: SBAdminViewService.json_dumps_for_url(params_payload)
            },
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

    def autocomplete(
        self,
        view_id: str,
        field_name: str,
        search: str = "",
        page: int = 1,
    ) -> list[dict]:
        """Query an autocomplete filter widget — useful for resolving FK values.

        Looks up the ``SBAdminField`` named ``field_name`` on the
        ``view_id`` admin, finds its ``AutocompleteFilterWidget``, and
        runs the same ``search`` the browser dropdown calls. Use the
        returned ``value`` field as the filter value when calling
        ``list_rows`` for that column.

        Example: to find an agent by their queue, autocomplete the
        ``queue`` field on the agents admin to discover the queue's id,
        then ``list_rows`` with ``filter_data={"queue": [{"value": id,
        "label": name}]}``.

        Args:
          view_id: ``"<app_label>_<model_name>"`` from ``list_admins``.
          field_name: the ``SBAdminField`` ``name`` from the admin's
            ``fields`` list (the one whose ``filter.widget`` is
            ``"AutocompleteFilterWidget"``).
          search: free text term sent to the widget's ``search``.
          page: 1-indexed page number; widgets paginate at
            ``AUTOCOMPLETE_PAGE_SIZE`` (20).

        Returns ``[{"value": ..., "label": ...}, ...]``.
        """
        request = self.request
        ensure_sbadmin_request_data(request)
        admin = resolve_admin(view_id)
        admin.init_view_dynamic(request, request.request_data)

        widget = resolve_filter_widget(admin, request, field_name)

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
            modifier=widget.get_id(),
        )
        return json.loads(response.content.decode())["data"]
