import json
import logging
import math
from typing import Any, TYPE_CHECKING

from django.contrib.admin.utils import lookup_spawns_duplicates
from django.db.models import Q, Field
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import SafeString
from django.utils.text import smart_split, unescape_string_literal

from django_smartbase_admin.engine.const import (
    XLSX_PAGE_CHUNK_SIZE,
    SELECTED_ROWS_KWARG_NAME,
    SELECT_ALL_KEYWORD,
    DESELECTED_ROWS_KWARG_NAME,
    URL_PARAMS_NAME,
    FILTER_DATA_NAME,
    TABLE_PARAMS_NAME,
    SELECTION_DATA_NAME,
    BASE_PARAMS_NAME,
    TABLE_PARAMS_PAGE_NAME,
    COLUMNS_DATA_NAME,
    TABLE_PARAMS_SIZE_NAME,
    COLUMNS_DATA_COLUMNS_NAME,
    COLUMNS_DATA_VISIBLE_NAME,
    COLUMNS_DATA_COLLAPSED_NAME,
    PAGE_SIZE_OPTIONS,
    PAGINATION_ACTIVE_RANGE,
    TABLE_PARAMS_SORT_NAME,
    COLUMNS_DATA_ORDER_NAME,
    OBJECT_ID_PLACEHOLDER,
    ANNOTATE_KEY,
    CONFIG_NAME,
    TABLE_PARAMS_FULL_TEXT_SEARCH,
    TABLE_PARAMS_SELECTED_FILTER_TYPE,
    ADVANCED_FILTER_DATA_NAME,
    IGNORE_LIST_SELECTION,
    MODIFIER_OBJECT_ID,
    SB_ADMIN_AJAX_NOTIFICATIONS_KEY,
)
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.utils import import_with_injection

QueryBuilderService = import_with_injection(
    "django_smartbase_admin.actions.advanced_filters", "QueryBuilderService"
)

if TYPE_CHECKING:
    from django_smartbase_admin.engine.field import SBAdminField

logger = logging.getLogger(__name__)


class SBAdminAction(object):
    view = None
    threadsafe_request = None

    def __init__(self, view, request) -> None:
        super().__init__()
        self.view = view
        self.threadsafe_request = request


class SBAdminListAction(SBAdminAction):
    def __init__(
        self,
        view,
        request,
        page_size=None,
        tabulator_definition=None,
        list_actions=None,
        all_params=None,
    ) -> None:
        super().__init__(view, request)
        if all_params is None:
            self.all_params = json.loads(
                request.request_data.request_get.get(BASE_PARAMS_NAME, "{}")
            )
            source_data = request.request_data.request_get.get(BASE_PARAMS_NAME, "{}")
            if (
                request.request_data.request_method == "POST"
                and request.headers.get("X-TabulatorRequest", None) == "true"
            ):
                source_data = request.body
            try:
                self.all_params = json.loads(source_data)
            except json.JSONDecodeError:
                pass
        else:
            self.all_params = all_params
        if not self.all_params:
            self.all_params = {}
        self.params = self.all_params.get(self.view.get_id(), {})
        self.filter_data = self.params.get(FILTER_DATA_NAME, {})
        self.advanced_filter_data = self.params.get(ADVANCED_FILTER_DATA_NAME, {})
        self.table_params = self.params.get(TABLE_PARAMS_NAME, {})
        self.columns_data = self.params.get(COLUMNS_DATA_NAME, {})
        self.selection_data = self.params.get(SELECTION_DATA_NAME, {})
        self.selected_rows = self.selection_data.get(
            SELECTED_ROWS_KWARG_NAME, SELECT_ALL_KEYWORD
        )
        self.deselected_rows = self.selection_data.get(DESELECTED_ROWS_KWARG_NAME, [])
        self.page_size = page_size or self.table_params.get(
            TABLE_PARAMS_SIZE_NAME, self.view.get_list_per_page(request)
        )
        self.init_column_fields()
        self.tabulator_definition = tabulator_definition
        self.list_actions = list_actions
        # Non-column row keys that survive ``_strip_to_visible_keys``.
        # Plugins emitting their own row keys extend this set.
        self.allowed_framework_keys: set[str] = {
            "_row_actions",
            "_children",
            "_sbadmin_tree_last_child",
        }

    def get_columns(self) -> list[str]:
        return self.view.get_list_display(self.threadsafe_request)

    def init_column_fields(self) -> None:
        column_fields: list["SBAdminField"] = []
        field_map = self.view.get_field_map(self.threadsafe_request)
        for column in self.get_columns():
            field = field_map.get(column, None)
            if field:
                column_fields.append(field)
        self.column_fields = column_fields

    def get_filters(self):
        return [field for field in self.column_fields if field.filter_widget]

    def get_tabulator_columns_add_id_column_if_missing(self, add_id_column=True):
        columns_serialized = []
        id_column_name = None
        for field in self.column_fields:
            if getattr(field.model_field, "primary_key", False):
                id_column_name = field.field
            columns_serialized.append(field.serialize_tabulator())
        # Add ID column in case there is none
        if add_id_column and not id_column_name:
            model_id_field = self.get_pk_field()
            id_column_name = model_id_field.name
            id_field = self.view.auto_create_field_from_model_field(model_id_field)
            id_field.title = "ID"
            id_field.list_visible = False
            id_field.init_field_static(
                self.view, self.threadsafe_request.request_data.configuration
            )
            columns_serialized = [id_field.serialize_tabulator()] + columns_serialized
        return columns_serialized, id_column_name

    def get_excel_columns(self):
        visible_fields = self.get_visible_column_fields()
        order = self.columns_data.get(COLUMNS_DATA_ORDER_NAME) or []
        by_field = {field.field: field for field in visible_fields}
        ordered = [by_field[name] for name in order if name in by_field]
        used = {field.field for field in ordered}
        ordered.extend(field for field in visible_fields if field.field not in used)
        return [field.serialize_xlsx() for field in ordered]

    def get_template_data(self):
        context_data = self.view.get_context_data(self.threadsafe_request)
        constants = {
            "OBJECT_ID_PLACEHOLDER": OBJECT_ID_PLACEHOLDER,
            "SELECT_ALL_KEYWORD": SELECT_ALL_KEYWORD,
            "SELECTED_ROWS_KWARG_NAME": SELECTED_ROWS_KWARG_NAME,
            "DESELECTED_ROWS_KWARG_NAME": DESELECTED_ROWS_KWARG_NAME,
            "URL_PARAMS_NAME": URL_PARAMS_NAME,
            "SELECTION_DATA_NAME": SELECTION_DATA_NAME,
            "COLUMNS_DATA_NAME": COLUMNS_DATA_NAME,
            "COLUMNS_DATA_ORDER_NAME": COLUMNS_DATA_ORDER_NAME,
            "COLUMNS_DATA_COLUMNS_NAME": COLUMNS_DATA_COLUMNS_NAME,
            "COLUMNS_DATA_VISIBLE_NAME": COLUMNS_DATA_VISIBLE_NAME,
            "COLUMNS_DATA_COLLAPSED_NAME": COLUMNS_DATA_COLLAPSED_NAME,
            "TABLE_PARAMS_NAME": TABLE_PARAMS_NAME,
            "TABLE_PARAMS_SIZE_NAME": TABLE_PARAMS_SIZE_NAME,
            "TABLE_PARAMS_FULL_TEXT_SEARCH": TABLE_PARAMS_FULL_TEXT_SEARCH,
            "TABLE_PARAMS_SELECTED_FILTER_TYPE": TABLE_PARAMS_SELECTED_FILTER_TYPE,
            "FILTER_DATA_NAME": FILTER_DATA_NAME,
            "ADVANCED_FILTER_DATA_NAME": ADVANCED_FILTER_DATA_NAME,
            "BASE_PARAMS_NAME": BASE_PARAMS_NAME,
            "TABLE_PARAMS_PAGE_NAME": TABLE_PARAMS_PAGE_NAME,
            "TABLE_PARAMS_SORT_NAME": TABLE_PARAMS_SORT_NAME,
            "PAGE_SIZE_OPTIONS": PAGE_SIZE_OPTIONS,
            "PAGINATION_ACTIVE_RANGE": PAGINATION_ACTIVE_RANGE,
            "ANNOTATE_KEY": ANNOTATE_KEY,
            "CONFIG_NAME": CONFIG_NAME,
            "AJAX_NOTIFICATIONS_KEY": SB_ADMIN_AJAX_NOTIFICATIONS_KEY,
        }

        columns, id_column_name = self.get_tabulator_columns_add_id_column_if_missing()
        row_actions = self.view.get_sbadmin_row_actions_processed(
            self.threadsafe_request
        )
        if row_actions:
            columns.append(
                {
                    "field": "_row_actions",
                    "title": "",
                    "headerSort": False,
                    "frozen": True,
                    "sbadminKeepDataWidth": True,
                    "sbadminSystemColumn": True,
                    "hozAlign": "right",
                    "formatter": "sbadminRowActionsFormatter",
                    "cssClass": "row-actions-cell",
                }
            )
        tabulator_definition = (
            self.tabulator_definition
            or self.view.get_tabulator_definition(self.threadsafe_request)
        )
        tabulator_definition["tableColumns"] = columns
        tabulator_definition["tableIdColumnName"] = id_column_name
        tabulator_definition["constants"] = constants

        list_actions = (
            self.view.process_list_actions(self.threadsafe_request, self.list_actions)
            if self.list_actions is not None
            else self.view.get_sbadmin_list_actions_processed(self.threadsafe_request)
        )

        context_data.update(
            {
                "const": constants,
                "tabulator_definition": tabulator_definition,
                "id_column_name": id_column_name,
                "filters": self.get_filters(),
                "advanced_filters_data": QueryBuilderService.get_advanced_filters_context_data(
                    self
                ),
                "filters_template_name": self.view.get_filters_template_name(
                    self.threadsafe_request
                ),
                "tabulator_header_template_name": self.view.get_tabulator_header_template_name(
                    self.threadsafe_request
                ),
                "search_fields": self.view.get_search_fields(self.threadsafe_request),
                "search_field_placeholder": self.view.get_search_field_placeholder(
                    self.threadsafe_request
                ),
                "list_actions": list_actions,
                "list_selection_actions": self.view.get_sbadmin_list_selection_actions_grouped(
                    self.threadsafe_request
                ),
                "config_url": self.view.get_config_url(self.threadsafe_request),
                "new_url": (
                    self.view.get_new_url(self.threadsafe_request)
                    if self.view.has_add_permission(self.threadsafe_request)
                    else None
                ),
                **self.view.get_config_data(self.threadsafe_request),
            }
        )
        return context_data

    def get_order_by_from_request(self) -> list[str]:
        order_by = []
        for sort in self.table_params.get("sort", []):
            order_by.append(f"{'-' if sort['dir'] == 'desc' else ''}{sort['field']}")
        if len(order_by) == 0:
            order_by = self.view.get_list_ordering(self.threadsafe_request) or [
                self.get_pk_field().name
            ]
        return order_by

    def get_order_by_fields_from_request(self) -> list["SBAdminField"]:
        order_by = self.get_order_by_from_request()
        order_by_fields = []
        order_by_fields_names = set()
        for field in order_by:
            field_name = field[1:] if field.startswith("-") else field
            order_by_fields_names.add(field_name)
        for field in self.column_fields:
            if field.field in order_by_fields_names:
                order_by_fields.append(field)
        return order_by_fields

    def get_filter_from_request(self):
        base_filters = SBAdminViewService.get_filter_from_request(
            self.threadsafe_request, self.column_fields, self.filter_data
        )
        advanced_filters = QueryBuilderService.get_filters_for_list_action(self)
        return base_filters & advanced_filters

    def get_search_fields(self, request):
        search_fields_definition = self.view.get_search_fields(request)
        search_fields = []
        for field in self.column_fields:
            if field.name in search_fields_definition:
                search_fields.append(field)
        return search_fields

    def get_filter_fields_from_request(self) -> list["SBAdminField"]:
        filter_fields: list["SBAdminField"] = list(
            SBAdminViewService.get_filter_fields_and_values_from_request(
                self.threadsafe_request,
                self.column_fields,
                self.filter_data,
            ).keys()
        )
        filter_fields.extend(
            QueryBuilderService.get_filters_fields_for_list_action(self)
        )
        filter_fields.extend(self.get_order_by_fields_from_request())
        if self.is_search_query():
            search_fields = self.get_search_fields(self.threadsafe_request)
            filter_fields.extend(search_fields)
        return filter_fields

    def get_annotates(self, visible_fields=None):
        column_fields = (
            visible_fields if visible_fields is not None else self.column_fields
        )
        return SBAdminViewService.get_annotates(
            self.view.model, self.get_data_queryset_values(), column_fields
        )

    def get_data_queryset(self, visible_fields=None):
        return self.view.get_queryset(self.threadsafe_request).annotate(
            **self.get_annotates(visible_fields)
        )

    def get_visible_column_fields(self) -> list["SBAdminField"]:
        columns_data_dict = self.columns_data.get(COLUMNS_DATA_COLUMNS_NAME, {})
        return [
            field
            for field in self.column_fields
            if columns_data_dict.get(
                field.field, {COLUMNS_DATA_VISIBLE_NAME: field.list_visible}
            )[COLUMNS_DATA_VISIBLE_NAME]
        ]

    def get_pk_field(self) -> Field:
        return SBAdminViewService.get_pk_field_for_model(self.view.model)

    def get_data_queryset_values(self) -> list[str]:
        values = [self.get_pk_field().name]
        visible_column_fields = self.get_visible_column_fields()
        values.extend([field.field for field in visible_column_fields])
        # Include supporting_annotates keys for visible columns
        for field in visible_column_fields:
            if field.supporting_annotates:
                values.extend(field.supporting_annotates.keys())
        if self.view.sbadmin_list_display_data:
            values.extend(self.view.sbadmin_list_display_data)
        # Include fields required by active filters, ordering, and search, even if hidden
        values.extend([field.field for field in self.get_filter_fields_from_request()])
        return values

    def get_search_results(self, request, queryset, search_term):
        """
        Return a tuple containing a queryset to implement the search
        and a boolean indicating if the results may contain duplicates.
        """

        def construct_search(field_name):
            prefix = field_name[0] if field_name and field_name[0] in "^=@" else ""
            raw_field_name = field_name[1:] if prefix else field_name
            return self.view.get_search_lookup(request, raw_field_name, prefix)

        search_fields = self.get_search_fields(request)
        search_fields_definition = list(self.view.get_search_fields(request) or [])
        if search_fields_definition and search_term:
            search_field_map = {
                field.name: str(field.filter_field) for field in search_fields
            }
            orm_lookups = []
            for configured_search_field in search_fields_definition:
                configured_search_field = str(configured_search_field)
                if not configured_search_field:
                    continue
                prefix = (
                    configured_search_field[0]
                    if configured_search_field[0] in "^=@"
                    else ""
                )
                raw_field_name = (
                    configured_search_field[1:] if prefix else configured_search_field
                )
                lookup_field = search_field_map.get(raw_field_name, raw_field_name)
                orm_lookups.append(construct_search(f"{prefix}{lookup_field}"))
            term_queries = []
            for bit in smart_split(search_term):
                if bit.startswith(('"', "'")) and bit[0] == bit[-1]:
                    bit = unescape_string_literal(bit)
                or_queries = Q.create(
                    [(orm_lookup, bit) for orm_lookup in orm_lookups],
                    connector=Q.OR,
                )
                term_queries.append(or_queries)
            queryset = queryset.filter(Q.create(term_queries))
            if any(
                lookup_spawns_duplicates(self.view.model._meta, search_spec)
                for search_spec in orm_lookups
            ):
                logger.warning(
                    "%s full-text search can duplicate rows because current "
                    "search_fields traverse relations. Prefer SBAdmin field names "
                    "(SBAdminField.name) in search_fields so SBAdmin can map them "
                    "through filter_field to direct ORM lookups.",
                    self.view.__class__.__name__,
                )
        return queryset

    def is_search_query(self):
        full_text_search_query_value = self.filter_data.get(
            TABLE_PARAMS_FULL_TEXT_SEARCH, None
        )
        return bool(full_text_search_query_value)

    def search_in_queryset(self, base_qs):
        full_text_search_query_value = self.filter_data.get(
            TABLE_PARAMS_FULL_TEXT_SEARCH, None
        )
        if not full_text_search_query_value:
            return base_qs
        base_qs = self.get_search_results(
            self.threadsafe_request, base_qs, full_text_search_query_value
        )
        return base_qs

    def build_final_data_count_queryset(
        self, additional_filter=None, apply_plugins=True
    ):
        additional_filter = additional_filter or Q()
        filter_fields = self.get_filter_fields_from_request()
        base_qs = (
            self.get_data_queryset(visible_fields=filter_fields)
            .filter(self.get_filter_from_request())
            .filter(additional_filter)
        )
        base_qs = self.search_in_queryset(base_qs)
        if apply_plugins:
            request = self.threadsafe_request
            plugins = list(request.request_data.configuration.plugins)
            for plugin in plugins:
                base_qs = plugin.modify_count_queryset(
                    self,
                    request=request,
                    qs=base_qs,
                )
        return base_qs

    def build_final_data_queryset(
        self, page_num, page_size, additional_filter=None, apply_plugins=True
    ):
        """Return the sliced data qs for the current page.

        ``apply_plugins=False`` is the escape hatch plugins use to
        re-enter this method and grab the raw filtered+ordered qs
        without recursing back into their own hooks.
        """
        additional_filter = additional_filter or Q()
        from_item = (page_num - 1) * page_size
        to_item = page_num * page_size
        values = list(self.get_data_queryset_values())
        base_qs = self.get_data_queryset().values(*values)

        request = self.threadsafe_request
        plugins = (
            list(request.request_data.configuration.plugins) if apply_plugins else []
        )
        for plugin in plugins:
            base_qs = plugin.modify_base_queryset(
                self,
                request=request,
                qs=base_qs,
                values=values,
            )

        base_qs = base_qs.filter(self.get_filter_from_request()).filter(
            additional_filter
        )
        base_qs = self.search_in_queryset(base_qs)
        base_qs = base_qs.order_by(*self.get_order_by_from_request())
        if apply_plugins:
            for plugin in plugins:
                base_qs = plugin.modify_data_queryset(
                    self,
                    request=request,
                    qs=base_qs,
                    page_num=page_num,
                    page_size=page_size,
                )
        return base_qs[from_item:to_item]

    def get_data(self, page_num=None, page_size=None, additional_filter=None):
        additional_filter = additional_filter or Q()

        page_num = page_num or int(self.table_params.get(TABLE_PARAMS_PAGE_NAME, 1))
        page_size = page_size or self.page_size

        total_count = self.build_final_data_count_queryset(additional_filter).count()

        data_qs = self.build_final_data_queryset(page_num, page_size, additional_filter)
        data = list(data_qs)

        self.process_final_data(data)
        request = self.threadsafe_request
        plugins = list(request.request_data.configuration.plugins)
        for plugin in plugins:
            data = plugin.modify_final_data(
                self,
                request=request,
                data=data,
            )

        raw_rows_by_pk = {row[self.get_pk_field().name]: dict(row) for row in data}
        self.inject_row_actions(data, raw_rows_by_pk=raw_rows_by_pk)

        return {
            "last_page": math.ceil(total_count / page_size),
            "data": data,
            "last_row": total_count,
        }

    def process_final_data(self, final_data: list[dict[str, Any]]) -> None:
        visible_columns = self.get_visible_column_fields()
        field_key_field_map: dict[str, "SBAdminField"] = {
            field.field: field for field in visible_columns
        }
        for row in final_data:
            obj_id = row.get(self.get_pk_field().name, None)
            additional_data = {}
            if self.view.sbadmin_list_display_data:
                additional_data = {
                    data: row.get(data, None)
                    for data in self.view.sbadmin_list_display_data
                }
            # Include supporting_annotates values in additional_data
            for field in visible_columns:
                if field.supporting_annotates:
                    for key in field.supporting_annotates.keys():
                        additional_data[key] = row.get(key, None)
            for field_key, value in row.items():
                if field_key in field_key_field_map:
                    field = field_key_field_map[field_key]
                    value = self.view.process_field_data(
                        self.threadsafe_request, field, obj_id, value, additional_data
                    )
                if isinstance(value, str) and not isinstance(value, SafeString):
                    value = escape(value)
                row[field_key] = value

    def inject_row_actions(
        self, final_data: list[dict[str, Any]], raw_rows_by_pk: dict | None = None
    ) -> None:
        actions = self.view.get_sbadmin_row_actions_processed(self.threadsafe_request)
        if not actions:
            return
        pk_field = self.get_pk_field().name
        for row in final_data:
            obj_id = row.get(pk_field)
            raw_row = (raw_rows_by_pk or {}).get(obj_id)
            row["_row_actions"] = [
                descriptor
                for action in actions
                if (
                    descriptor := self._materialize_row_action(
                        action, row, obj_id, raw_row=raw_row
                    )
                )
                is not None
            ]

    def _materialize_row_action(
        self, action, row: dict[str, Any], obj_id: Any, raw_row=None
    ) -> dict[str, Any] | None:
        action_row = raw_row or row
        if not action.is_enabled(action_row):
            return None

        url = action.url
        if url and MODIFIER_OBJECT_ID in url:
            url = url.replace(MODIFIER_OBJECT_ID, str(obj_id))

        return {
            "url": url,
            "title": str(action.get_title(action_row) or ""),
            "icon": action.get_icon(action_row),
            "css_class": action.get_css_class(action_row) or "",
            "open_in_modal": bool(action.open_in_modal),
            "is_method_action": bool(action.action_id) and not action.open_in_modal,
            "open_in_new_tab": bool(action.open_in_new_tab),
        }

    def get_json_data(self):
        data = self.get_data()
        self._strip_to_visible_keys(data.get("data") or [])
        return data

    def _strip_to_visible_keys(self, rows: list[dict[str, Any]]) -> None:
        """Keep PK + visible columns + ``allowed_framework_keys``; drop the rest."""
        if not rows:
            return
        allowed = {field.field for field in self.get_visible_column_fields()}
        allowed.add(self.get_pk_field().name)
        allowed |= self.allowed_framework_keys
        for row in rows:
            for key in list(row.keys()):
                if key not in allowed:
                    row.pop(key, None)

    def get_graph_data(self, order_by=None, annotate_x=None, annotate_y=None):
        order_by = order_by or []
        data_queryset = self.get_data_queryset()
        data_queryset = data_queryset.filter(self.get_filter_from_request()).order_by(
            order_by
        )
        final_data = list(data_queryset)
        return final_data

    def get_selection_queryset(self):
        if not self.selection_data:
            # don't run with no selection data as it will result in querying all records
            return Q(id__in=[])
        additional_filter = None
        if self.selected_rows and self.selected_rows != SELECT_ALL_KEYWORD:
            additional_filter = Q(id__in=self.selected_rows)

        if self.selected_rows == SELECT_ALL_KEYWORD:
            additional_filter = ~Q(id__in=self.deselected_rows)
        return additional_filter

    def get_xlsx_data(self, request):
        page_size = XLSX_PAGE_CHUNK_SIZE
        file_name = (
            f'{self.view.get_menu_label()}__{timezone.now().strftime("%Y-%m-%d")}.xlsx'
        )
        columns = self.get_excel_columns()
        additional_filter = Q()
        if request.request_data.modifier != IGNORE_LIST_SELECTION:
            additional_filter = self.get_selection_queryset()
        data_list = []
        report_data = self.get_data(
            page_size=page_size,
            page_num=1,
            additional_filter=additional_filter,
        )
        data_list.extend(report_data["data"])
        for i in range(1, report_data["last_page"]):
            data_list.extend(
                self.get_data(
                    page_size=page_size,
                    page_num=i + 1,
                    additional_filter=additional_filter,
                )["data"]
            )
        plugins = list(request.request_data.configuration.plugins)
        for plugin in plugins:
            data_list = plugin.modify_xlsx_data(
                self,
                request=request,
                data=data_list,
            )
        options = (
            self.view.get_sbadmin_xlsx_options(request).to_json()
            if self.view.get_sbadmin_xlsx_options(request)
            else {}
        )
        return [file_name, data_list, columns, options]
