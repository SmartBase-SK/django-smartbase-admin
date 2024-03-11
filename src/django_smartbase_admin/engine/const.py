from enum import Enum


class Action(Enum):
    LIST = "list"
    LIST_JSON = "action_list_json"
    TABLE_REORDER_ACTION = "action_table_reorder"
    ENTER_REORDER = "action_enter_reorder"
    LIST_JSON_REORDER = "action_list_json_reorder"
    TABLE_DATA_EDIT = "action_table_data_edit"
    DASHBOARD = "dashboard"
    DETAIL = "detail"
    AUTOCOMPLETE = "action_autocomplete"
    CONFIG = "action_config"
    XLSX_EXPORT = "action_xlsx_export"
    BULK_DELETE = "action_bulk_delete"


class Formatter(Enum):
    IMAGE = "image"
    DETAIL_LINK = "detail_link"


DEFAULT_PAGE_SIZE = 20
PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
AUTOCOMPLETE_PAGE_SIZE = 20
XLSX_PAGE_CHUNK_SIZE = 50000
NEW_OBJECT_ID = 0
OBJECT_ID_PLACEHOLDER = -1
ALL_MODEL_FIELDS = "__all__"
DYNAMIC_VIEW_PREFIX = "_dv_"

SELECT_ALL_KEYWORD = "__all__"
SELECTED_ROWS_KWARG_NAME = "table_selected_rows"
DESELECTED_ROWS_KWARG_NAME = "table_deselected_rows"
URL_PARAMS_NAME = "url_params"
SELECTION_DATA_NAME = "selectionData"
COLUMNS_DATA_NAME = "columnsData"
COLUMNS_DATA_ORDER_NAME = "order"
COLUMNS_DATA_COLUMNS_NAME = "columns"
COLUMNS_DATA_VISIBLE_NAME = "visible"
COLUMNS_DATA_COLLAPSED_NAME = "collapsed"
TABLE_PARAMS_NAME = "tableParams"
TABLE_PARAMS_SIZE_NAME = "size"
TABLE_PARAMS_PAGE_NAME = "page"
TABLE_PARAMS_SORT_NAME = "sort"
FILTER_DATA_NAME = "filterData"
BASE_PARAMS_NAME = "params"
AUTOCOMPLETE_SEARCH_NAME = "__search_term__"
AUTOCOMPLETE_FORWARD_NAME = "__forward_data__"
AUTOCOMPLETE_PAGE_NUM = "__requestedPage__"
GLOBAL_FILTER_DATA_KEY = "global_filter_data"
GLOBAL_FILTER_ALIAS_WIDGET_ID = "global_alias"
TRANSLATION_MODEL_KEY = "model_table"
PAGINATION_ACTIVE_RANGE = 5
MULTISELECT_FILTER_MAX_CHOICES_SHOWN = 3
ANNOTATE_KEY = "_annt"
CONFIG_NAME = "config_name"
DETAIL_STRUCTURE_RIGHT_CLASS = "detail-structure-right"
TRANSLATIONS_SELECTED_LANGUAGES = "translation_selected_languages"
OVERRIDE_CONTENT_OF_NOTIFICATION = "override_notification_content"
