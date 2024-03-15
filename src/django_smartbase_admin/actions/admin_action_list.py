import json
import math

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone

from django_smartbase_admin.engine.actions import SBAdminAction
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
)
from django_smartbase_admin.services.views import SBAdminViewService


class SBAdminListAction(SBAdminAction):
    def __init__(
        self,
        view,
        request,
        page_size=None,
        tabulator_definition=None,
        list_actions=None,
    ) -> None:
        super().__init__(view, request)
        self.all_params = json.loads(
            request.request_data.request_get.get(f"{BASE_PARAMS_NAME}", "{}")
        )
        if not self.all_params:
            self.all_params = {}
        self.params = self.all_params.get(self.view.get_id(), {})
        self.filter_data = self.params.get(FILTER_DATA_NAME, {})
        self.table_params = self.params.get(TABLE_PARAMS_NAME, {})
        self.columns_data = self.params.get(COLUMNS_DATA_NAME, {})
        self.selection_data = self.params.get(SELECTION_DATA_NAME, {})
        self.selected_rows = self.selection_data.get(
            SELECTED_ROWS_KWARG_NAME, SELECT_ALL_KEYWORD
        )
        self.deselected_rows = self.selection_data.get(DESELECTED_ROWS_KWARG_NAME, [])
        self.page_size = page_size or self.table_params.get(
            TABLE_PARAMS_SIZE_NAME, self.view.get_list_per_page()
        )
        self.init_column_fields()
        self.tabulator_definition = tabulator_definition
        self.list_actions = list_actions

    def get_columns(self):
        return self.view.get_list_display(self.threadsafe_request)

    def init_column_fields(self):
        column_fields = []
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
        values = self.get_data_queryset_values()
        return [
            field.serialize_xlsx()
            for field in self.column_fields
            if field.field in values
        ]

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
            "FILTER_DATA_NAME": FILTER_DATA_NAME,
            "BASE_PARAMS_NAME": BASE_PARAMS_NAME,
            "TABLE_PARAMS_PAGE_NAME": TABLE_PARAMS_PAGE_NAME,
            "TABLE_PARAMS_SORT_NAME": TABLE_PARAMS_SORT_NAME,
            "PAGE_SIZE_OPTIONS": PAGE_SIZE_OPTIONS,
            "PAGINATION_ACTIVE_RANGE": PAGINATION_ACTIVE_RANGE,
            "ANNOTATE_KEY": ANNOTATE_KEY,
            "CONFIG_NAME": CONFIG_NAME,
        }

        columns, id_column_name = self.get_tabulator_columns_add_id_column_if_missing()
        tabulator_definition = (
            self.tabulator_definition
            or self.view.get_tabulator_definition(self.threadsafe_request)
        )
        tabulator_definition["tableColumns"] = columns
        tabulator_definition["tableIdColumnName"] = id_column_name
        tabulator_definition["constants"] = constants

        context_data.update(
            {
                "const": constants,
                "tabulator_definition": tabulator_definition,
                "id_column_name": id_column_name,
                "filters": self.get_filters(),
                "list_actions": self.list_actions
                or self.view._get_sbadmin_list_actions(),
                "list_selection_actions": self.view.get_sbadmin_list_selection_actions(),
                "config_url": self.view.get_config_url(),
                "new_url": (
                    self.view.get_new_url()
                    if self.view.has_add_permission(self.threadsafe_request)
                    else None
                ),
                **self.view.get_config_data(self.threadsafe_request),
            }
        )
        return context_data

    def get_order_by_from_request(self):
        order_by = []
        for sort in self.table_params.get("sort", []):
            order_by.append(f"{'-' if sort['dir'] == 'desc' else ''}{sort['field']}")
        if len(order_by) == 0:
            order_by = self.view.get_list_ordering() or [self.get_pk_field().name]
        return order_by

    def get_filter_from_request(self):
        return SBAdminViewService.get_filter_from_request(
            self.threadsafe_request, self.column_fields, self.filter_data
        )

    def get_filter_fields_from_request(self):
        return list(
            SBAdminViewService.get_filter_fields_and_values_from_request(
                self.threadsafe_request, self.column_fields, self.filter_data
            ).keys()
        )

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

    def get_visible_column_fields(self):
        columns_data_dict = self.columns_data.get(COLUMNS_DATA_COLUMNS_NAME, {})
        return [
            field
            for field in self.column_fields
            if columns_data_dict.get(
                field.field, {COLUMNS_DATA_VISIBLE_NAME: field.list_visible}
            )[COLUMNS_DATA_VISIBLE_NAME]
        ]

    def get_pk_field(self):
        return SBAdminViewService.get_pk_field_for_model(self.view.model)

    def get_data_queryset_values(self):
        values = [self.get_pk_field().name]
        visible_column_fields = self.get_visible_column_fields()
        values.extend([field.field for field in visible_column_fields])
        if self.view.sbadmin_list_display_data:
            values.extend(self.view.sbadmin_list_display_data)
        return values

    def get_data(self, page_num=None, page_size=None, additional_filter=None):
        data_queryset = self.get_data_queryset()
        additional_filter = additional_filter or Q()

        page_num = page_num or int(self.table_params.get(TABLE_PARAMS_PAGE_NAME, 1))
        page_size = page_size or self.page_size

        from_item = (page_num - 1) * page_size
        to_item = page_num * page_size

        base_qs = (
            data_queryset.values(*self.get_data_queryset_values())
            .filter(self.get_filter_from_request())
            .filter(additional_filter)
        )
        filter_fields = self.get_filter_fields_from_request()
        total_count = (
            self.get_data_queryset(visible_fields=filter_fields)
            .filter(self.get_filter_from_request())
            .filter(additional_filter)
            .count()
        )
        final_data = list(
            base_qs.order_by(*self.get_order_by_from_request())[from_item:to_item]
        )

        self.process_final_data(final_data)
        return {
            "last_page": math.ceil(total_count / page_size),
            "data": final_data,
            "last_row": total_count,
        }

    def process_final_data(self, final_data):
        visible_columns = self.get_visible_column_fields()
        fields_with_methods_to_call = [
            field
            for field in visible_columns
            if field.view_method or field.python_formatter
        ]
        for row in final_data:
            additional_data = {}
            if self.view.sbadmin_list_display_data:
                additional_data = {
                    data: row.get(data, None)
                    for data in self.view.sbadmin_list_display_data
                }
            for field in fields_with_methods_to_call:
                object_id = row.get(self.get_pk_field().name, None)
                value = row.get(field.field, None)
                processed_value = value
                if field.view_method:
                    processed_value = field.view_method(
                        object_id, value, **additional_data
                    )
                formatted_value = processed_value
                if field.python_formatter:
                    formatted_value = field.python_formatter(object_id, processed_value)
                row[field.field] = formatted_value

    def get_json_data(self):
        return self.get_data()

    def get_graph_data(self, order_by=None, annotate_x=None, annotate_y=None):
        order_by = order_by or []
        data_queryset = self.get_data_queryset()
        data_queryset = data_queryset.filter(self.get_filter_from_request()).order_by(
            order_by
        )
        final_data = list(data_queryset)
        return final_data

    def get_selection_queryset(self):
        additional_filter = None
        if self.selected_rows and self.selected_rows != SELECT_ALL_KEYWORD:
            additional_filter = Q(id__in=self.selected_rows)

        if self.selected_rows == SELECT_ALL_KEYWORD:
            additional_filter = ~Q(id__in=self.deselected_rows)
        return additional_filter

    def get_xlsx_data(self):
        page_size = XLSX_PAGE_CHUNK_SIZE
        file_name = (
            f'{self.view.get_menu_label()}__{timezone.now().strftime("%Y-%m-%d")}.xlsx'
        )
        columns = self.get_excel_columns()
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
        options = (
            self.view.get_sbadmin_xlsx_options().to_json()
            if self.view.get_sbadmin_xlsx_options()
            else {}
        )
        return [file_name, data_list, columns, options]
