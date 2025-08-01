import json
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.actions import delete_selected
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminFormViewAction,
)
from django_smartbase_admin.engine.const import (
    Action,
    OBJECT_ID_PLACEHOLDER,
    URL_PARAMS_NAME,
    MULTISELECT_FILTER_MAX_CHOICES_SHOWN,
    AUTOCOMPLETE_PAGE_SIZE,
    CONFIG_NAME,
    DETAIL_STRUCTURE_RIGHT_CLASS,
    GLOBAL_FILTER_ALIAS_WIDGET_ID,
    OVERRIDE_CONTENT_OF_NOTIFICATION,
    FilterVersions,
    BASE_PARAMS_NAME,
    TABLE_RELOAD_DATA_EVENT_NAME,
    TABLE_UPDATE_ROW_DATA_EVENT_NAME,
    SELECT_ALL_KEYWORD,
    IGNORE_LIST_SELECTION,
    SUPPORTED_FILE_TYPE_ICONS,
)
from django_smartbase_admin.services.configuration import (
    SBAdminUserConfigurationService,
)
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.services.xlsx_export import (
    SBAdminXLSXExportService,
    SBAdminXLSXOptions,
    SBAdminXLSXFormat,
)
from django_smartbase_admin.utils import is_htmx_request, render_notifications, is_modal

if TYPE_CHECKING:
    from django_smartbase_admin.engine.field import SBAdminField

SBADMIN_IS_MODAL_VAR = "sbadmin_is_modal"
SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR = "sbadmin_parent_instance_field"
SBADMIN_PARENT_INSTANCE_PK_VAR = "sbadmin_parent_instance_pk"
SBADMIN_PARENT_INSTANCE_LABEL_VAR = "sbadmin_parent_instance_label"
SBADMIN_RELOAD_ON_SAVE_VAR = "sbadmin_reload_on_save"


class SBAdminBaseView(object):
    menu_label = None
    global_filter_data_map = None
    field_cache = None
    sbadmin_detail_actions = None
    delete_confirmation_template = "sb_admin/actions/delete_confirmation.html"

    def init_view_static(self, configuration, model, admin_site):
        pass

    def get_id(self):
        raise NotImplementedError

    def get_menu_label(self) -> str:
        return self.menu_label or self.model._meta.verbose_name_plural

    def has_permission(self, request, obj=None, permission=None) -> bool:
        return SBAdminViewService.has_permission(
            request=request, view=self, model=self.model, obj=obj, permission=permission
        )

    def has_add_permission(self, request, obj=None) -> bool:
        return self.has_permission(request, obj, "add")

    def has_view_permission(self, request, obj=None) -> bool:
        return self.has_permission(request, obj, "view")

    def has_change_permission(self, request, obj=None) -> bool:
        return self.has_permission(request, obj, "change")

    def has_delete_permission(self, request, obj=None) -> bool:
        return self.has_permission(request, obj, "delete")

    def has_permission_for_action(self, request, action: SBAdminCustomAction) -> bool:
        return self.has_permission(
            request=request,
            obj=None,
            permission=action,
        )

    def has_view_or_change_permission(self, request, obj=None) -> bool:
        return self.has_view_permission(request, obj) or self.has_change_permission(
            request, obj
        )

    def delegate_to_action_view(self, processed_action):
        def inner_view(request, modifier):
            return processed_action.target_view.as_view(view=self)(request)

        return inner_view

    def process_actions(
        self, request, actions: list[SBAdminCustomAction]
    ) -> list[SBAdminCustomAction]:
        processed_actions = self.process_actions_permissions(request, actions)
        for processed_action in processed_actions:
            if isinstance(processed_action, SBAdminFormViewAction):
                action_id = processed_action.target_view.__name__
                setattr(
                    self,
                    action_id,
                    self.delegate_to_action_view(processed_action),
                )
                processed_action.url = self.get_action_url(action_id)
                processed_action.action_id = action_id

        return processed_actions

    def process_actions_permissions(
        self, request, actions: list[SBAdminCustomAction]
    ) -> list[SBAdminCustomAction]:
        result = []
        for action in actions:
            if self.has_permission_for_action(request, action):
                result.append(action)
        return result

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied

    def get_field_map(self, request):
        return self.field_cache

    def init_fields_cache(self, fields_source, configuration, force=False):
        if not force and self.field_cache:
            return self.field_cache.values()
        from django_smartbase_admin.engine.field import SBAdminField

        fields = []
        self.field_cache = {}
        for field in fields_source:
            if not isinstance(field, SBAdminField):
                field = SBAdminField(name=field)
            field.init_field_static(self, configuration)
            fields.append(field)
            self.field_cache[field.name] = field
        return fields

    def action_view(self, request, action=None, modifier=None):
        action_function = getattr(self, action, None)
        if not action_function:
            raise Http404
        action = SBAdminCustomAction(
            title=action, view=self, action_id=action, action_modifier=modifier
        )
        permitted_action = self.has_permission_for_action(request, action)
        if not permitted_action:
            raise PermissionDenied
        return action_function(request, modifier)

    def get_action_url(self, action, modifier="template"):
        raise NotImplementedError

    def register_autocomplete_views(self, request):
        pass

    def action_autocomplete(self, request, modifier):
        autocomplete_view = request.request_data.configuration.autocomplete_map.get(
            modifier
        )
        if not autocomplete_view:
            self.register_autocomplete_views(request)
        autocomplete_view = request.request_data.configuration.autocomplete_map.get(
            modifier
        )
        autocomplete_view.init_view_dynamic(request, request.request_data)
        return autocomplete_view.action_autocomplete(request, modifier)

    def auto_create_field_from_model_field(self, model_field):
        from django_smartbase_admin.engine.field import SBAdminField

        field = SBAdminField(name=model_field.name, auto_created=True)
        field.model_field = model_field
        return field

    def get_username_data(self, request) -> dict[str, Any]:
        if request.request_data.user.first_name and request.request_data.user.last_name:
            return {
                "full_name": f"{request.request_data.user.first_name} {request.request_data.user.last_name}",
                "initials": f"{request.request_data.user.first_name[0]}{request.request_data.user.last_name[0]}",
            }
        return {
            "full_name": request.request_data.user.username,
            "initials": request.request_data.user.username[0],
        }

    def get_sbadmin_detail_actions(
        self, request, object_id: int | str | None = None
    ) -> Iterable[SBAdminCustomAction] | None:
        return self.sbadmin_detail_actions

    def get_color_scheme_context(self, request):
        from django_smartbase_admin.views.user_config_view import ColorSchemeForm

        user_config = SBAdminUserConfigurationService.get_user_config(request)
        color_scheme_form = ColorSchemeForm(instance=user_config)
        return {
            "user_config": user_config,
            "color_scheme_form": color_scheme_form,
        }

    def get_global_context(
        self, request, object_id: int | str | None = None
    ) -> dict[str, Any]:
        return {
            "view_id": self.get_id(),
            "configuration": request.request_data.configuration,
            "request_data": request.request_data,
            "DETAIL_STRUCTURE_RIGHT_CLASS": DETAIL_STRUCTURE_RIGHT_CLASS,
            "OVERRIDE_CONTENT_OF_NOTIFICATION": OVERRIDE_CONTENT_OF_NOTIFICATION,
            "username_data": self.get_username_data(request),
            "detail_actions": self.get_sbadmin_detail_actions(request, object_id),
            SBADMIN_IS_MODAL_VAR: is_modal(request),
            SBADMIN_RELOAD_ON_SAVE_VAR: SBADMIN_RELOAD_ON_SAVE_VAR in request.GET
            or SBADMIN_RELOAD_ON_SAVE_VAR in request.POST,
            "const": json.dumps(
                {
                    "MULTISELECT_FILTER_MAX_CHOICES_SHOWN": MULTISELECT_FILTER_MAX_CHOICES_SHOWN,
                    "AUTOCOMPLETE_PAGE_SIZE": AUTOCOMPLETE_PAGE_SIZE,
                    "GLOBAL_FILTER_ALIAS_WIDGET_ID": GLOBAL_FILTER_ALIAS_WIDGET_ID,
                    "TABLE_RELOAD_DATA_EVENT_NAME": TABLE_RELOAD_DATA_EVENT_NAME,
                    "TABLE_UPDATE_ROW_DATA_EVENT_NAME": TABLE_UPDATE_ROW_DATA_EVENT_NAME,
                    "SELECT_ALL_KEYWORD": SELECT_ALL_KEYWORD,
                    "SUPPORTED_FILE_TYPE_ICONS": SUPPORTED_FILE_TYPE_ICONS,
                    "STATIC_BASE_PATH": f"{settings.STATIC_URL}sb_admin",
                }
            ),
            **self.get_color_scheme_context(request),
        }

    def get_model_path(self) -> str:
        return SBAdminViewService.get_model_path(self.model)

    def process_field_data(
        self,
        request,
        field: "SBAdminField",
        obj_id: Any,
        value: Any,
        additional_data: dict[str, Any],
    ) -> Any:
        is_xlsx_export = request.request_data.action == Action.XLSX_EXPORT.value
        if field.view_method:
            value = field.view_method(obj_id, value, **additional_data)
        if is_xlsx_export and getattr(field.xlsx_options, "python_formatter", None):
            value = field.xlsx_options.python_formatter(obj_id, value)
        elif field.python_formatter:
            value = field.python_formatter(obj_id, value)
        return value


class SBAdminBaseQuerysetMixin(object):
    def get_queryset(self, request=None):
        request_data = getattr(request, "request_data", None)
        qs = SBAdminViewService.get_restricted_queryset(
            self.model,
            request,
            request_data,
            global_filter=True,
            global_filter_data_map=self.global_filter_data_map,
        )
        return qs


class SBAdminBaseListView(SBAdminBaseView):
    sbadmin_list_view_config = None
    sbadmin_list_display = None
    sbadmin_list_display_data = None
    sbadmin_list_selection_actions = None
    sbadmin_list_actions = None
    sbadmin_list_filter = None
    sbadmin_xlsx_options = None
    sbadmin_table_history_enabled = True
    sbadmin_list_reorder_field = None
    search_field_placeholder = _("Search...")
    filters_version = None
    sbadmin_actions_initialized = False
    sbadmin_list_action_class = SBAdminListAction

    def activate_reorder(self, request) -> None:
        request.reorder_active = True

    def action_list_json_reorder(self, request, modifier) -> JsonResponse:
        self.activate_reorder(request)
        return self.action_list_json(request, modifier, page_size=100)

    def action_enter_reorder(self, request, modifier):
        self.activate_reorder(request)
        tabulator_definition = self.get_tabulator_definition(request)
        tabulator_definition["modules"] = [
            "tableParamsModule",
            "movableColumnsModule",
        ]
        tabulator_definition["defaultColumnData"] = {
            "headerSort": False,
            "resizable": False,
        }
        tabulator_definition["tableHistoryEnabled"] = False
        tabulator_definition["tableAjaxUrl"] = self.get_action_url(
            Action.LIST_JSON_REORDER.value
        )
        return self.action_list(
            request,
            page_size=100,
            tabulator_definition=tabulator_definition,
            list_actions=[
                SBAdminCustomAction(
                    title=_(f"Exit Reorder"),
                    url=self.get_menu_view_url(request),
                ),
            ],
            template=self.reorder_list_template,
        )

    def is_reorder_active(self, request) -> bool:
        return (
            self.is_reorder_available(request)
            and getattr(request, "reorder_active", False) == True
        )

    def is_reorder_available(self, request) -> str | None:
        return self.sbadmin_list_reorder_field

    def action_table_reorder(self, request, modifier) -> JsonResponse:
        self.activate_reorder(request)
        qs = self.get_queryset(request)
        pk_field = SBAdminViewService.get_pk_field_for_model(self.model).name
        old_order = dict(
            qs.values_list(pk_field, self.sbadmin_list_reorder_field).order_by(
                *self.get_list_ordering(request)
            )
        )
        current_row_id = json.loads(request.POST.get("currentRowId", ""))
        replaced_row_id = json.loads(request.POST.get("replacedRowId", ""))
        old_order_ids = list(old_order.keys())
        current_row_index = old_order_ids.index(current_row_id)
        new_order_ids = [*old_order_ids]
        del new_order_ids[current_row_index]
        if not replaced_row_id:
            new_order_ids.append(current_row_id)
        else:
            replaced_row_index = new_order_ids.index(replaced_row_id)
            new_order_ids.insert(replaced_row_index, current_row_id)
        diff_dict = defaultdict(list)
        for position, item_id in enumerate(new_order_ids):
            old_position = old_order[item_id]
            diff = (position + 1) - int(old_position)
            diff_dict[diff].append(item_id)
        for diff, item_ids in diff_dict.items():
            qs.filter(**{f"{pk_field}__in": item_ids}).update(
                **{
                    self.sbadmin_list_reorder_field: F(self.sbadmin_list_reorder_field)
                    + int(diff)
                }
            )
        return JsonResponse({"message": request.POST})

    def action_table_data_edit(self, request, modifier) -> HttpResponse:
        current_row_id = json.loads(request.POST.get("currentRowId", ""))
        column_field_name = request.POST.get("columnFieldName", "")
        cell_value = request.POST.get("cellValue", "")
        messages.add_message(request, messages.ERROR, "Not Implemented")
        return HttpResponse(status=200, content=render_notifications(request))

    def init_actions(self, request) -> None:
        if self.sbadmin_actions_initialized:
            return
        self.process_actions(request, self.get_sbadmin_list_selection_actions(request))
        self.sbadmin_actions_initialized = True

    def init_view_dynamic(self, request, request_data=None, **kwargs) -> None:
        super().init_view_dynamic(request, request_data, **kwargs)
        self.init_fields_cache(
            self.get_sbadmin_list_display(request), request.request_data.configuration
        )
        self.init_actions(request)

    def get_sbadmin_list_display(self, request) -> list[str] | list:
        return self.sbadmin_list_display or self.list_display or []

    def register_autocomplete_views(self, request) -> None:
        super().register_autocomplete_views(request)
        self.init_fields_cache(
            self.get_sbadmin_list_display(request),
            request.request_data.configuration,
            force=True,
        )
        for list_action in self.get_sbadmin_list_selection_actions(request):
            if isinstance(list_action, SBAdminFormViewAction):
                form = list_action.target_view.form_class
                form.view = self
                form()

    def get_list_display(self, request) -> list[str] | list:
        return [
            getattr(field, "name", field)
            for field in self.get_sbadmin_list_display(request)
        ]

    def get_search_fields(self, request):
        if hasattr(super(SBAdminBaseListView, self), "get_search_fields"):
            return super().get_search_fields(request)
        else:
            return []

    def get_list_ordering(self, request) -> Iterable[str] | list:
        return self.ordering or []

    def get_list_initial_order(self, request) -> list[dict[str, Any]]:
        order = []
        for order_field in self.get_list_ordering(request):
            direction = "desc" if order_field.startswith("-") else "asc"
            order.append(
                {
                    "field": order_field[1:] if direction == "desc" else order_field,
                    "dir": direction,
                }
            )
        return order

    def get_list_per_page(self, request) -> int | None:
        return self.list_per_page

    def has_add_permission(self, request, obj=None) -> bool:
        if self.is_reorder_active(request):
            return False
        return super().has_add_permission(request)

    def get_tabulator_definition(self, request) -> dict[str, Any]:
        view_id = self.get_id()
        tabulator_definition = {
            "viewId": view_id,
            "advancedFilterId": f"{view_id}" + "-advanced-filter",
            "filterFormId": f"{view_id}" + "-filter-form",
            "columnWidgetId": f"{view_id}" + "-column-widget",
            "paginationWidgetId": f"{view_id}" + "-pagination-widget",
            "pageSizeWidgetId": f"{view_id}" + "-page-size-widget",
            "baseViewUrl": request.path,
            "tableElSelector": f"#{view_id}-table",
            "tableAjaxUrl": self.get_ajax_url(),
            "tableDataEditUrl": self.get_action_url(Action.TABLE_DATA_EDIT.value),
            "tableActionMoveUrl": self.get_action_url(
                Action.TABLE_REORDER_ACTION.value
            ),
            "tableDetailUrl": self.get_detail_url(),
            "tableInitialSort": self.get_list_initial_order(request),
            "tableInitialPageSize": self.get_list_per_page(request),
            "tableHistoryEnabled": self.sbadmin_table_history_enabled,
            # used to initialize all columns with these values
            "defaultColumnData": {},
            "locale": request.LANGUAGE_CODE,
            "modules": [
                "viewsModule",
                "selectionModule",
                "columnDisplayModule",
                "filterModule",
                "tableParamsModule",
                "detailViewModule",
            ],
            "tabulatorOptions": {
                "renderVertical": "basic",
                "persistence": False,
                "layoutColumnsOnNewData": True,
                "height": "100%",
                "ajaxContentType": "json",
                "ajaxConfig": {
                    "headers": {
                        "Content-type": "application/json; charset=utf-8",
                    },
                },
                "responsiveLayout": "collapse",
                "pagination": True,
                "paginationMode": "remote",
                "filterMode": "remote",
                "sortMode": "remote",
                "selectable": "highlight",
            },
        }
        if self.get_filters_version(request) == FilterVersions.FILTERS_VERSION_2:
            tabulator_definition["modules"].extend(
                [
                    "advancedFilterModule",
                    "fullTextSearchModule",
                    "headerTabsModule",
                ]
            )
        return tabulator_definition

    def _get_sbadmin_list_actions(self, request) -> list[SBAdminCustomAction] | list:
        list_actions = [*(self.get_sbadmin_list_actions(request) or [])]
        if self.is_reorder_available(request):
            list_actions = [
                *list_actions,
                SBAdminCustomAction(
                    title=_(f"Reorder {self.model._meta.verbose_name}"),
                    view=self,
                    action_id=Action.ENTER_REORDER.value,
                    no_params=True,
                ),
            ]
        return list_actions

    def get_sbadmin_list_actions(self, request) -> list[SBAdminCustomAction]:
        if not self.sbadmin_list_actions:
            self.sbadmin_list_actions = [
                SBAdminCustomAction(
                    title=_("Download XLSX"),
                    view=self,
                    action_id=Action.XLSX_EXPORT.value,
                    action_modifier=IGNORE_LIST_SELECTION,
                )
            ]
        return self.sbadmin_list_actions

    def get_sbadmin_list_selection_actions(self, request) -> list[SBAdminCustomAction]:
        if not self.sbadmin_list_selection_actions:
            self.sbadmin_list_selection_actions = [
                SBAdminCustomAction(
                    title=_("Export Selected"),
                    view=self,
                    action_id=Action.XLSX_EXPORT.value,
                ),
                SBAdminCustomAction(
                    title=_("Delete Selected"),
                    view=self,
                    action_id=Action.BULK_DELETE.value,
                    css_class="btn-destructive",
                ),
            ]
        return self.sbadmin_list_selection_actions

    def get_sbadmin_list_selection_actions_grouped(
        self, request
    ) -> dict[str, list[SBAdminCustomAction]]:
        result = {}
        list_selection_actions = self.process_actions(
            request, self.get_sbadmin_list_selection_actions(request)
        )
        for action in list_selection_actions:
            if not result.get(action.group):
                result.update({action.group: []})
            result[action.group].append(action)
        return result

    def get_sbadmin_xlsx_options(self, request) -> SBAdminXLSXOptions:
        self.sbadmin_xlsx_options = self.sbadmin_xlsx_options or SBAdminXLSXOptions(
            header_cell_format=SBAdminXLSXFormat(
                bg_color="#00aaa7", font_color="#ffffff", bold=True
            ),
            cell_format=SBAdminXLSXFormat(text_wrap=True),
            default_row_height=15,
            header_rows_count=1,
            header_rows_freeze=True,
        )
        return self.sbadmin_xlsx_options

    def action_xlsx_export(self, request, modifier) -> HttpResponse:
        action = self.sbadmin_list_action_class(self, request)
        data = action.get_xlsx_data(request)
        return SBAdminXLSXExportService.create_workbook_http_respone(*data)

    def action_bulk_delete(self, request, modifier):
        action = self.sbadmin_list_action_class(self, request)
        if (
            request.request_data.request_method == "POST"
            and request.headers.get("X-TabulatorRequest", None) == "true"
        ):
            return redirect(
                self.get_action_url("action_bulk_delete")
                + "?"
                + urllib.parse.urlencode(
                    {BASE_PARAMS_NAME: json.dumps(action.all_params)}
                )
            )
        if not action.selection_data:
            # don't run with no selection data as it will result in delete of all records
            messages.error(request, _("No selection made."))
            return redirect(self.get_menu_view_url(request))
        additional_filter = action.get_selection_queryset()
        response = delete_selected(
            self, request, self.get_queryset(request).filter(additional_filter)
        )
        if not response:
            return redirect(self.get_menu_view_url(request))
        return response

    def action_config(self, request, config_id=None):
        from django_smartbase_admin.models import SBAdminListViewConfiguration

        config_id = config_id if config_id != "None" else None

        config_name = request.POST.get(CONFIG_NAME, None)
        if config_name:
            config_name = urllib.parse.unquote(config_name)
        updated_configuration = None
        if request.request_data.request_method == "POST":
            config_params = {}
            if config_id:
                config_params["id"] = config_id
            elif config_name:
                config_params["name"] = config_name
            if config_params:
                (
                    updated_configuration,
                    created,
                ) = SBAdminListViewConfiguration.objects.update_or_create(
                    user_id=request.request_data.user.id,
                    **config_params,
                    defaults={
                        "url_params": request.request_data.request_post.get(
                            URL_PARAMS_NAME
                        ),
                        "view": self.get_id(),
                        "action": None,
                        "modifier": None,
                    },
                )
        if request.request_data.request_method == "DELETE":
            if config_id:
                SBAdminListViewConfiguration.objects.by_user_id(
                    request.request_data.user.id
                ).by_id(config_id).by_view_action_modifier(view=self.get_id()).delete()

        redirect_to = self.get_redirect_url_from_request(request, updated_configuration)

        response = redirect(redirect_to)
        if is_htmx_request(request.request_data.request_meta):
            response = HttpResponse()
            response["HX-Redirect"] = redirect_to
        return response

    def get_redirect_url_from_request(self, request, updated_configuration=None):
        referer = request.request_data.request_meta.get("HTTP_REFERER", "")
        url = urllib.parse.urlparse(referer)
        query = dict(urllib.parse.parse_qsl(url.query))
        query.update({"tabCreated": True})
        if updated_configuration:
            query.update({"selectedView": updated_configuration.pk})
        url = url._replace(query=urllib.parse.urlencode(query))
        redirect_to = urllib.parse.urlunparse(url)
        return redirect_to

    def action_list(
        self,
        request,
        page_size=None,
        tabulator_definition=None,
        extra_context=None,
        list_actions=None,
        template=None,
    ):
        action = self.sbadmin_list_action_class(
            self,
            request,
            page_size=page_size,
            tabulator_definition=tabulator_definition,
            list_actions=list_actions,
        )
        data = action.get_template_data()

        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        extra_context.update(
            {
                "content_context": data,
                "model_name": self.model._meta.verbose_name,
                "list_title": self.model._meta.verbose_name_plural,
            }
        )

        return TemplateResponse(
            request,
            template
            or self.change_list_template
            or [
                "admin/%s/%s/change_list.html"
                % (self.model._meta.app_label, self.model._meta.model_name),
                "admin/%s/change_list.html" % self.model._meta.app_label,
                "admin/change_list.html",
            ],
            extra_context,
        )

    def action_list_json(self, request, modifier, page_size=None) -> JsonResponse:
        action = self.sbadmin_list_action_class(self, request, page_size=page_size)
        data = action.get_json_data()
        return JsonResponse(data=data, safe=False)

    def get_sbadmin_list_filter(self, request) -> Iterable | None:
        return self.sbadmin_list_filter

    def get_all_config(self, request) -> dict[str, Any]:
        all_config = {"name": _("All"), "url_params": {}, "default": True}
        list_filter = self.get_sbadmin_list_filter(request) or []
        if not list_filter:
            return all_config
        list_fields = self.get_sbadmin_list_display(request) or []
        self.init_fields_cache(list_fields, request.request_data.configuration)
        base_filter = {
            getattr(field, "filter_field", field): ""
            for field in list_fields
            if field in list_filter
            or getattr(field, "name", None) in list_filter
            or getattr(field, "filter_field", None) in list_filter
        }
        url_params = None
        if base_filter:
            url_params = {"filterData": base_filter}
        all_config = {
            "name": _("All"),
            "url_params": url_params,
            "all_params_changed": True,
        }
        return all_config

    def get_sbadmin_list_view_config(self, request) -> list:
        return self.sbadmin_list_view_config or []

    def get_base_config(self, request) -> list[dict[str, Any]]:
        sbadmin_list_config = self.get_sbadmin_list_view_config(request)
        list_view_config = [self.get_all_config(request), *sbadmin_list_config]
        views = []
        for defined_view in list_view_config:
            url_params = SBAdminViewService.process_url_params(
                view_id=self.get_id(),
                url_params=defined_view["url_params"],
                filter_version=self.get_filters_version(request),
            )
            views.append(
                {
                    "name": defined_view["name"],
                    "url_params": SBAdminViewService.json_dumps_for_url(url_params),
                    "default": True,
                }
            )
        return views

    def get_config_data(self, request) -> dict[str, list[dict[str, Any]]]:
        from django_smartbase_admin.models import SBAdminListViewConfiguration

        current_views = list(
            SBAdminListViewConfiguration.objects.by_user_id(
                request.request_data.user.id
            )
            .by_view_action_modifier(view=self.get_id())
            .values()
        )
        for view in current_views:
            view["detail_url"] = self.get_config_url(request, view["id"])
        config_views = self.get_base_config(request)
        config_views.extend(current_views)
        return {"current_views": config_views}

    def get_ajax_url(self) -> str:
        return self.get_action_url(Action.LIST_JSON.value)

    def get_detail_url(self) -> str:
        url = reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": Action.DETAIL.value,
                "modifier": "template",
            },
        )
        return f"{url}/{OBJECT_ID_PLACEHOLDER}"

    def get_config_url(self, request, config_name=None) -> str:
        return self.get_action_url(Action.CONFIG.value, config_name)

    def get_new_url(self, request) -> None:
        return None

    def get_context_data(self, request) -> dict:
        return {}

    def get_filters_version(self, request) -> FilterVersions:
        return (
            self.filters_version or request.request_data.configuration.filters_version
        )

    def get_filters_template_name(self, request) -> str:
        filters_version = self.get_filters_version(request)
        if filters_version is FilterVersions.FILTERS_VERSION_2:
            return "sb_admin/components/filters_v2.html"
        else:
            # default
            return "sb_admin/components/filters.html"

    def get_tabulator_header_template_name(self, request) -> str:
        filters_version = self.get_filters_version(request)
        if filters_version is FilterVersions.FILTERS_VERSION_2:
            return "sb_admin/actions/partials/tabulator_header_v2.html"
        else:
            # default
            return "sb_admin/actions/partials/tabulator_header_v1.html"

    def get_search_field_placeholder(self, request) -> str:
        return self.search_field_placeholder
