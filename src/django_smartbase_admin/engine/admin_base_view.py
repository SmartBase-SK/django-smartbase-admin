import json
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from copy import copy
from typing import Any, TYPE_CHECKING

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.actions import delete_selected
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db.models import F, Q
from django.http import HttpResponse, JsonResponse, HttpRequest, Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminRowAction,
    sbadmin_action,
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
    SB_ADMIN_AJAX_NOTIFICATIONS_KEY,
    TABLE_RELOAD_DATA_EVENT_NAME,
    TABLE_UPDATE_ROW_DATA_EVENT_NAME,
    SELECT_ALL_KEYWORD,
    IGNORE_LIST_SELECTION,
    MODIFIER_OBJECT_ID,
    SUPPORTED_FILE_TYPE_ICONS,
    ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR,
)
from django_smartbase_admin.audit.views import should_link_history_to_audit
from django_smartbase_admin.engine.inline_pagination import SBADMIN_INLINE_PREFIX_HEADER
from django_smartbase_admin.services.configuration import (
    SBAdminUserConfigurationService,
)
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.services.xlsx_export import (
    SBAdminXLSXExportService,
    SBAdminXLSXOptions,
    SBAdminXLSXFormat,
)
from django_smartbase_admin.utils import (
    is_htmx_request,
    is_modal,
    render_notifications,
    render_notifications_if_any,
)

if TYPE_CHECKING:
    from django_smartbase_admin.engine.field import SBAdminField

SBADMIN_IS_MODAL_VAR = "sbadmin_is_modal"
SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR = "sbadmin_parent_instance_field"
SBADMIN_PARENT_INSTANCE_PK_VAR = "sbadmin_parent_instance_pk"
SBADMIN_PARENT_INSTANCE_LABEL_VAR = "sbadmin_parent_instance_label"
SBADMIN_RELOAD_ON_SAVE_VAR = "sbadmin_reload_on_save"


class SBAdminBaseView(object):
    global_filter_data_map = None
    sbadmin_detail_actions = None
    menu_label: str | None = None
    add_label: str | None = None
    change_label: str | None = None
    delete_confirmation_template = "sb_admin/actions/delete_confirmation.html"
    widgets = None
    widget_views = None

    def init_view_static(self, configuration, model, admin_site):
        self.init_widgets_static(configuration)

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

    def delegate_to_target_view(self, target_view, action=None):
        def inner_view(request, modifier, object_id):
            return target_view.as_view(view=self)(
                request, modifier=modifier, object_id=object_id
            )

        inner_view._is_sbadmin_action = True
        if action is not None:
            inner_view._sbadmin_action_attrs = {
                "permission": getattr(action, "permission", None)
            }
        return inner_view

    def process_list_actions(
        self,
        request,
        actions: list[SBAdminCustomAction],
        object_id: int | str | None = None,
    ) -> list[SBAdminCustomAction]:
        resolved_actions = self._resolve_action_urls(
            actions,
            object_id,
        )
        return self.process_actions_permissions(request, resolved_actions)

    def process_row_actions(
        self, request, actions: list[SBAdminCustomAction]
    ) -> list[SBAdminCustomAction]:
        resolved_actions = self._resolve_action_urls(actions, MODIFIER_OBJECT_ID)
        return self.process_actions_permissions(request, resolved_actions)

    def process_detail_actions(
        self,
        request,
        actions: list[SBAdminCustomAction],
        object_id: int | str | None = None,
    ) -> list[SBAdminCustomAction]:
        resolved_actions = self._resolve_action_urls(actions, object_id)
        return self.process_actions_permissions(request, resolved_actions)

    def process_inline_actions(
        self,
        request,
        actions: list[SBAdminCustomAction],
        object_id: int | str | None = None,
    ) -> list[SBAdminCustomAction]:
        resolved_actions = self._resolve_action_urls(actions, object_id)
        return self.process_actions_permissions(request, resolved_actions)

    def _resolve_action_urls(
        self, actions: list[SBAdminCustomAction], object_id: int | str | None = None
    ) -> list[SBAdminCustomAction]:
        return [self._resolve_action_url(action, object_id) for action in actions]

    def _resolve_action_url(
        self, action: SBAdminCustomAction, object_id: int | str | None = None
    ) -> SBAdminCustomAction:
        if action.sub_actions:
            resolved_sub_actions = self._resolve_action_urls(
                action.sub_actions, object_id
            )
            if resolved_sub_actions != action.sub_actions:
                action = copy(action)
                action.sub_actions = resolved_sub_actions
            return action
        target_view = getattr(action, "target_view", None)
        source_view = getattr(action, "view", None) or self
        if target_view is not None:
            resolved_action = copy(action)
            action_id = source_view._register_form_view_action(
                target_view, getattr(action, "action_id", None), action
            )
            resolved_action.action_id = action_id
            resolved_action.url = source_view.get_action_url(
                action_id,
                modifier=getattr(action, "action_modifier", None) or "template",
                object_id=object_id,
            )
            return resolved_action
        if action.url:
            return action
        if getattr(action, "view", None) and getattr(action, "action_id", None):
            resolved_action = copy(action)
            resolved_action.url = source_view.get_action_url(
                action.action_id,
                modifier=getattr(action, "action_modifier", None) or "template",
                object_id=object_id,
            )
            return resolved_action
        return action

    def _register_form_view_action(
        self, target_view, action_id=None, action=None
    ) -> str:
        # Mutates the admin singleton: attaches a synthetic delegate
        # method named after the modal's ``action_id`` so URL dispatch
        # (and MCP invocation) can reach it via ``getattr(admin,
        # action_id)``. Idempotent — the ``hasattr`` guard skips
        # already-registered ids on subsequent calls.
        action_id = action_id or getattr(target_view, "action_id", None)
        action_id = action_id or target_view.__name__
        if not hasattr(self, action_id):
            setattr(self, action_id, self.delegate_to_target_view(target_view, action))
        return action_id

    def process_actions(
        self, request, actions: list[SBAdminCustomAction]
    ) -> list[SBAdminCustomAction]:
        resolved_actions = self._resolve_action_urls(actions)
        return self.process_actions_permissions(request, resolved_actions)

    def process_actions_permissions(
        self, request, actions: list[SBAdminCustomAction]
    ) -> list[SBAdminCustomAction]:
        result = []
        for action in actions:
            if not self.has_permission_for_action(request, action):
                continue
            if action.sub_actions:
                sub_actions = self.process_actions_permissions(
                    request, action.sub_actions
                )
                if not sub_actions:
                    continue
                if sub_actions != action.sub_actions:
                    action = copy(action)
                    action.sub_actions = sub_actions
            result.append(action)
        return result

    def get_widgets(self):
        return self.widgets or []

    def get_widget_views(self, request, object_id=None):
        return self.widget_views or []

    def get_widget_id(self, widget, index):
        return getattr(widget, "widget_id", None)

    def get_widget_parent_view(self, widget):
        return None

    def init_widget_view_static(self, widget, configuration, index):
        widget.widget_id = self.get_widget_id(widget, index)
        widget.parent_view = self.get_widget_parent_view(widget)
        widget.init_widget_static(configuration)
        widget_id = widget.get_id()
        if widget_id:
            configuration.view_map[widget_id] = widget
        return widget

    def init_widgets_static(self, configuration) -> None:
        self.widget_views = []
        for index, widget_class in enumerate(self.get_widgets()):
            widget = widget_class() if isinstance(widget_class, type) else widget_class
            self.widget_views.append(
                self.init_widget_view_static(widget, configuration, index)
            )

    def init_widget_views_dynamic(self, request, request_data=None, **kwargs) -> None:
        object_id = getattr(request_data, "object_id", None)
        for widget in self.get_widget_views(request, object_id):
            widget.init_view_dynamic(request, request_data, **kwargs)

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        self.init_widget_views_dynamic(request, request_data, **kwargs)

    def get_field_map(self, request) -> dict[str, "SBAdminField"]:
        return self.init_fields_cache(
            self.get_effective_list_display(request),
            request.request_data.configuration,
            request=request,
        )

    def init_fields_cache(
        self, fields_source, configuration, force=False, request=None
    ):
        from django_smartbase_admin.engine.field import SBAdminField

        field_cache = {}
        for field in fields_source:
            if not isinstance(field, SBAdminField):
                field = SBAdminField(name=field)
            else:
                field = field.clone()
            field.init_field_static(self, configuration)
            field_cache[field.name] = field
        return field_cache

    def get_action_url_kwargs(
        self, action, modifier="template", object_id=None
    ) -> dict:
        kwargs = {
            "view": self.get_id(),
            "action": action,
            "modifier": modifier,
        }
        if object_id is not None:
            kwargs["object_id"] = object_id
        return kwargs

    def get_action_url(self, action, modifier="template", object_id=None):
        raise NotImplementedError

    def register_autocomplete_views(self, request):
        for step in self._autocomplete_registration_steps(request):
            step(request)

    def _autocomplete_registration_steps(self, request):
        return [
            step
            for step in (
                getattr(self, "_register_list_filter_autocomplete", None),
                getattr(self, "_register_form_autocomplete", None),
                getattr(self, "_register_inline_autocomplete", None),
            )
            if step is not None
        ]

    def _register_autocomplete_from_filter_fields(self, request, fields) -> None:
        from django_smartbase_admin.engine.filter_widgets import (
            AutocompleteFilterWidget,
        )

        for field in fields:
            widget = getattr(field, "filter_widget", None)
            if isinstance(widget, AutocompleteFilterWidget):
                request.request_data.register_autocomplete_view(widget)

    def register_action_autocomplete_views(
        self, request, actions: Iterable[SBAdminCustomAction] | None
    ) -> None:
        request_data = getattr(request, "request_data", None)
        requested_action_id, request_modifier = self.split_action_autocomplete_modifier(
            getattr(request_data, "modifier", None)
        )
        if not requested_action_id:
            return
        for action in actions or []:
            if getattr(action, "sub_actions", None):
                self.register_action_autocomplete_views(request, action.sub_actions)

            target_view = getattr(action, "target_view", None)
            if target_view is None:
                continue
            action_id = self.get_form_view_action_id(
                target_view, getattr(action, "action_id", None)
            )
            if requested_action_id and requested_action_id != action_id:
                continue

            source_view = getattr(action, "view", None) or self
            action_view = target_view(view=source_view)
            action_view.setup(
                request,
                modifier=request_modifier,
                object_id=getattr(request_data, "object_id", None),
            )
            form_class = (
                action_view.get_form_class()
                if hasattr(action_view, "get_form_class")
                else getattr(target_view, "form_class", None)
            )
            if not form_class:
                continue
            form_kwargs = (
                action_view.get_unbound_form_kwargs()
                if hasattr(action_view, "get_unbound_form_kwargs")
                else {"view": self}
            )
            from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit

            if issubclass(form_class, SBAdminBaseFormInit):
                form_kwargs.setdefault("view", self)
                form_kwargs["sbadmin_action_id"] = action_id
            form_class(**form_kwargs)

    @staticmethod
    def split_action_autocomplete_modifier(modifier):
        if not modifier or ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR not in modifier:
            return None, modifier
        action_id, widget_modifier = modifier.split(
            ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR, 1
        )
        if not action_id or not widget_modifier:
            return None, modifier
        return action_id, widget_modifier

    @staticmethod
    def get_form_view_action_id(target_view, action_id=None):
        return (
            action_id or getattr(target_view, "action_id", None) or target_view.__name__
        )

    @sbadmin_action(permission="view")
    def action_autocomplete(self, request, modifier, object_id=None):
        amap = request.request_data.autocomplete_map
        autocomplete_view = amap.get(modifier)
        if autocomplete_view is None:
            for step in self._autocomplete_registration_steps(request):
                step(request)
                autocomplete_view = amap.get(modifier)
                if autocomplete_view is not None:
                    break
        if autocomplete_view is None:
            self.register_autocomplete_views(request)
            autocomplete_view = amap.get(modifier)
        if autocomplete_view is None:
            raise Http404
        autocomplete_view.init_view_dynamic(request, request.request_data)
        return autocomplete_view.action_autocomplete(request, modifier, object_id)

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

    def get_sbadmin_detail_actions_processed(
        self, request, object_id: int | str | None = None
    ) -> list[SBAdminCustomAction]:
        return self.process_detail_actions(
            request,
            [*(self.get_sbadmin_detail_actions(request, object_id) or [])],
            object_id,
        )

    def get_sbadmin_fieldset_actions(
        self,
        request,
        fieldset,
        fieldset_data: dict[str, Any],
        object_id: int | str | None = None,
    ) -> Iterable[SBAdminCustomAction] | None:
        return fieldset_data.get("actions")

    def get_sbadmin_fieldset_actions_processed(
        self,
        request,
        fieldset,
        fieldset_data: dict[str, Any],
        object_id: int | str | None = None,
    ) -> list[SBAdminCustomAction]:
        return self.process_detail_actions(
            request,
            [
                *(
                    self.get_sbadmin_fieldset_actions(
                        request, fieldset, fieldset_data, object_id
                    )
                    or []
                )
            ],
            object_id,
        )

    def get_sbadmin_fieldsets_actions_processed(
        self, request, object_id: int | str | None = None
    ) -> list[SBAdminCustomAction]:
        if not hasattr(self, "get_sbadmin_fieldsets"):
            return []
        try:
            fieldsets = self.get_sbadmin_fieldsets(request, object_id) or []
        except ImproperlyConfigured as exc:
            if "missing definition of fieldsets or sbadmin_fieldsets" not in str(exc):
                raise
            return []
        actions = []
        for fieldset, fieldset_data in fieldsets:
            actions.extend(
                self.get_sbadmin_fieldset_actions_processed(
                    request, fieldset, fieldset_data, object_id
                )
            )
        return actions

    def get_color_scheme_context(self, request):
        from django_smartbase_admin.views.user_config_view import ColorSchemeForm

        user_config = SBAdminUserConfigurationService.get_user_config(request)
        color_scheme_form = ColorSchemeForm(instance=user_config)
        return {
            "user_config": user_config,
            "color_scheme_form": color_scheme_form,
        }

    def get_language_form_context(self, request):
        from django_smartbase_admin.views.user_config_view import LanguageForm

        language_form = None
        set_language_url = None
        if len(settings.LANGUAGES) > 1:
            try:
                set_language_url = reverse("set_language")
                language_form = LanguageForm(request=request)
            except NoReverseMatch:
                pass

        return {"language_form": language_form, "set_language_url": set_language_url}

    def get_add_label(
        self, request: HttpRequest, object_id: str | None = None
    ) -> str | None:
        return self.add_label

    def get_change_label(
        self, request: HttpRequest, object_id: str | None = None
    ) -> str | None:
        return self.change_label

    def get_change_view_context(
        self, request: HttpRequest, object_id: str | int | None
    ) -> dict[str, Any]:
        """Default change-form context: Back → ``back_url`` or model changelist.
        ModelAdmin only."""
        default_back = reverse(
            "sb_admin:{}_{}_changelist".format(
                self.opts.app_label, self.opts.model_name
            )
        )
        back_url = SBAdminViewService.resolve_back_url(
            request, default_back, current_path=request.path
        )
        return {
            "show_back_button": True,
            "back_url": back_url,
        }

    def get_global_context(
        self, request, object_id: int | str | None = None
    ) -> dict[str, Any]:
        return {
            "view_id": self.get_id(),
            "configuration": request.request_data.configuration,
            "request_data": request.request_data,
            "admin_title": request.request_data.configuration.get_admin_title(),
            "add_label": self.get_add_label(request, object_id),
            "change_label": self.get_change_label(request, object_id),
            "DETAIL_STRUCTURE_RIGHT_CLASS": DETAIL_STRUCTURE_RIGHT_CLASS,
            "OVERRIDE_CONTENT_OF_NOTIFICATION": OVERRIDE_CONTENT_OF_NOTIFICATION,
            "SBADMIN_INLINE_PREFIX_HEADER": SBADMIN_INLINE_PREFIX_HEADER,
            "username_data": self.get_username_data(request),
            "detail_actions": self.get_sbadmin_detail_actions_processed(
                request, object_id
            ),
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
                    "STATIC_URL": settings.STATIC_URL,
                    "STATIC_BASE_PATH": f"{settings.STATIC_URL}sb_admin",
                }
            ),
            **self.get_color_scheme_context(request),
            **self.get_language_form_context(request),
            **self.get_messaging_context(request),
        }

    def get_messaging_context(self, request) -> dict[str, Any]:
        """Inject the notification poller URL/interval when messaging is enabled.

        Kept defensive (returns ``{}`` on any error or when disabled) so the
        global context never breaks pages on projects without messaging.
        """
        try:
            from django_smartbase_admin.messaging.services import (
                SBAdminMessagingService,
            )

            return SBAdminMessagingService.get_poller_context(request)
        except Exception:
            return {}

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
            # MCP wants one canonical wire format. Bypass the built-in
            # locale-aware formatters (date / datetime / boolean) so the
            # JSON encoder emits raw values (ISO 8601 for dates, native
            # bools). Custom ``python_formatter``s still run — they
            # carry app logic the agent expects. Flag lives on
            # ``request`` because ``request_data`` gets rebuilt mid-flow.
            from django_smartbase_admin.engine.field_formatter import (
                LOCALE_DEPENDENT_FORMATTERS,
            )

            is_mcp = getattr(request, "is_mcp", False)
            if not (is_mcp and field.python_formatter in LOCALE_DEPENDENT_FORMATTERS):
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
    mcp_description = None
    sbadmin_list_display = None
    sbadmin_list_display_data = None
    sbadmin_list_selection_actions = None
    sbadmin_list_actions = None
    sbadmin_row_actions = None
    sbadmin_list_filter = None
    sbadmin_xlsx_options = None
    sbadmin_table_history_enabled = True
    sbadmin_list_history_enabled = True
    sbadmin_list_reorder_field = None
    sbadmin_nested: dict | None = None
    sbadmin_list_sticky_header_and_footer = None
    search_field_placeholder = _("Search...")
    filters_version = None
    sbadmin_actions_initialized = False
    sbadmin_list_action_class = SBAdminListAction
    pg_unaccent_ext_cache = {}

    def get_list_view_media(self, request):
        return forms.Media(js=("sb_admin/dist/table.js",))

    def get_extra_filter_from_request(self, request, list_action):
        return Q()

    @classmethod
    def _postgres_unaccent_extension_available(cls) -> bool:
        from django.conf import settings
        from django.db import connection

        if connection.vendor != "postgresql":
            return False
        if "django.contrib.postgres" not in settings.INSTALLED_APPS:
            return False
        alias = connection.alias
        cached = cls.pg_unaccent_ext_cache.get(alias)
        if cached is not None:
            return cached
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = %s LIMIT 1",
                    ["unaccent"],
                )
                available = bool(cursor.fetchone())
        except Exception:
            available = False
        cls.pg_unaccent_ext_cache[alias] = available
        return available

    def get_sbadmin_nested(self, request) -> dict | None:
        """Return the nested config dict for this view, or ``None`` for a flat list.

        Override for per-request logic. The returned dict must contain a
        ``parent_field`` key pointing at a self-referential ForeignKey.
        See ``plugins/nested.py`` for the full schema.
        """
        return self.sbadmin_nested

    def activate_reorder(self, request) -> None:
        request.reorder_active = True

    @sbadmin_action
    def action_list_json_reorder(
        self, request, modifier, object_id=None
    ) -> JsonResponse:
        self.activate_reorder(request)
        return self.action_list_json(
            request,
            modifier,
            object_id=object_id,
            page_size=100,
        )

    @sbadmin_action
    def action_enter_reorder(self, request, modifier, object_id=None):
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

    @sbadmin_action
    def action_table_reorder(self, request, modifier, object_id=None) -> JsonResponse:
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

    @sbadmin_action
    def action_table_data_edit(self, request, modifier, object_id=None) -> HttpResponse:
        current_row_id = json.loads(request.POST.get("currentRowId", ""))
        column_field_name = request.POST.get("columnFieldName", "")
        cell_value = request.POST.get("cellValue", "")
        messages.add_message(request, messages.ERROR, "Not Implemented")
        return HttpResponse(status=200, content=render_notifications(request))

    def init_actions(self, request) -> None:
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        all_actions = [
            *self.get_sbadmin_list_selection_actions_processed(request),
            *self.get_sbadmin_list_actions_processed(request),
            *self.get_sbadmin_row_actions_processed(request),
        ]
        if object_id is not None:
            all_actions.extend(
                self.get_sbadmin_detail_actions_processed(request, object_id)
            )
            all_actions.extend(
                self.get_sbadmin_fieldsets_actions_processed(request, object_id)
            )
        self.register_action_autocomplete_views(request, all_actions)

    def init_view_dynamic(self, request, request_data=None, **kwargs) -> None:
        super().init_view_dynamic(request, request_data, **kwargs)
        self.init_actions(request)

    def get_sbadmin_list_display(self, request) -> list[str] | list:
        return self.sbadmin_list_display or self.list_display or []

    def get_effective_list_display(self, request) -> list:
        """``get_sbadmin_list_display`` augmented with a synthetic,
        read-only primary-key column when the admin hasn't declared one.

        The list pipeline already emits every row's pk under a normalized
        ``"id"`` key, but without a matching field nothing can *select*,
        *sort*, or *filter* by it — the field map rejects the name (this is
        what made MCP ``list_rows(fields=["id"])`` fail, and why the browser
        only ever got a display-only id column). Promoting the pk to a real,
        hidden column closes that round-trip through the normal column /
        sort / filter machinery, for the UI and MCP alike. Hidden by default
        (``list_visible=False``) so it doesn't clutter the grid. With the pk
        now a real column, :meth:`get_tabulator_columns` reports its id-column
        name directly instead of grafting on a display-only one.
        """
        list_display = list(self.get_sbadmin_list_display(request) or [])
        pk_field = self._build_synthetic_pk_field(list_display)
        if pk_field is not None:
            list_display.append(pk_field)
        return list_display

    def _build_synthetic_pk_field(self, list_display):
        """Synthetic read-only pk column for the list — the canonical ``id``
        column the agent uses for select / sort / filter, and the frontend for
        row identity.

        Returns ``None`` when a declared column already addresses the pk — by
        name, by an explicit ``filter_field`` pointing at it, or via a method
        ``@admin.display(ordering="id")`` — since the author has already
        exposed it and a second column would be redundant; or when the pk
        can't be resolved (e.g. a composite pk).
        """
        from django_smartbase_admin.engine.filter_widgets import (
            PrimaryKeyFilterWidget,
        )

        model = getattr(self, "model", None)
        if model is None:
            return None
        pk_model_field = getattr(model._meta, "pk", None)
        pk_name = getattr(pk_model_field, "name", None)
        if not pk_name:
            return None

        for entry in list_display:
            name = getattr(entry, "name", entry)
            method = getattr(self, name, None) if isinstance(name, str) else None
            if (
                name == pk_name
                or getattr(entry, "filter_field", None) == pk_name
                or (
                    callable(method)
                    and getattr(method, "admin_order_field", None) == pk_name
                )
            ):
                return None

        field = self.auto_create_field_from_model_field(pk_model_field)
        field.title = "ID"
        field.list_visible = False  # off by default; still select/sort/filterable
        field.filter_widget = PrimaryKeyFilterWidget()
        return field

    def _register_list_filter_autocomplete(self, request) -> None:
        field_map = self.init_fields_cache(
            self.get_sbadmin_list_display(request),
            request.request_data.configuration,
            force=True,
            request=request,
        )
        if not field_map:
            return
        self._register_autocomplete_from_filter_fields(request, field_map.values())

    def get_list_display(self, request) -> list[str]:
        return [
            getattr(field, "name", field)
            for field in self.get_effective_list_display(request)
        ]

    def get_search_fields(self, request):
        if hasattr(super(SBAdminBaseListView, self), "get_search_fields"):
            return super().get_search_fields(request)
        return getattr(self, "search_fields", [])

    def get_search_lookup(self, request, field_name: str, prefix: str = "") -> str:
        if prefix == "^":
            return f"{field_name}__istartswith"
        if prefix == "=":
            return f"{field_name}__iexact"
        if prefix == "@":
            return f"{field_name}__search"
        if self._postgres_unaccent_extension_available():
            return f"{field_name}__unaccent__icontains"
        return f"{field_name}__icontains"

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

    def get_sbadmin_list_sticky_header_and_footer(self, request) -> bool:
        if self.sbadmin_list_sticky_header_and_footer is not None:
            return self.sbadmin_list_sticky_header_and_footer
        return request.request_data.configuration.default_list_sticky_header_and_footer

    def get_tabulator_definition(self, request) -> dict[str, Any]:
        view_id = self.get_id()
        sticky_header_and_footer = self.get_sbadmin_list_sticky_header_and_footer(
            request
        )
        tabulator_definition = {
            "viewId": view_id,
            "advancedFilterId": f"{view_id}" + "-advanced-filter",
            "filterFormId": f"{view_id}" + "-filter-form",
            "columnWidgetId": f"{view_id}" + "-column-widget",
            "paginationWidgetId": f"{view_id}" + "-pagination-widget",
            "pageSizeWidgetId": f"{view_id}" + "-page-size-widget",
            "baseViewUrl": request.path,
            "tableElSelector": f"#{view_id}-table",
            "tableAjaxUrl": self.get_ajax_url(request),
            "tableDataEditUrl": self.get_action_url(Action.TABLE_DATA_EDIT.value),
            "tableActionMoveUrl": self.get_action_url(
                Action.TABLE_REORDER_ACTION.value
            ),
            "tableDetailUrl": self.get_detail_url(),
            "tableInitialSort": self.get_list_initial_order(request),
            "tableInitialPageSize": self.get_list_per_page(request),
            "tableHistoryEnabled": self.sbadmin_table_history_enabled,
            "stickyHeaderAndFooter": sticky_header_and_footer,
            "enableUrlCompression": request.request_data.configuration.enable_url_compression,
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
                "dataTreeModule",
            ],
            "tabulatorOptions": {
                "renderVertical": "basic",
                "persistence": False,
                "layoutColumnsOnNewData": True,
                "layout": "fitDataFillAvailableSpace",
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
        for plugin in request.request_data.configuration.plugins:
            tabulator_definition = plugin.modify_tabulator_definition(
                self,
                request=request,
                definition=tabulator_definition,
            )
        if sticky_header_and_footer:
            tabulator_definition["modules"].append("stickyHeaderAndFooterModule")
        return tabulator_definition

    def get_sbadmin_list_actions_processed(
        self, request
    ) -> list[SBAdminCustomAction] | list:
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
        if self.sbadmin_list_history_enabled and should_link_history_to_audit(request):
            try:
                from django_smartbase_admin.audit.views import (
                    get_audit_model_history_url,
                )

                url = get_audit_model_history_url(self.model)
                list_actions = [
                    *list_actions,
                    SBAdminCustomAction(
                        title=_("History"),
                        url=url,
                        no_params=True,
                        permission="view",
                    ),
                ]
            except Exception:
                pass
        return self.process_list_actions(
            request,
            list_actions,
            object_id=getattr(
                getattr(request, "request_data", None), "object_id", None
            ),
        )

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
                    permission="delete",
                ),
            ]
        return self.sbadmin_list_selection_actions

    def get_sbadmin_list_selection_actions_processed(
        self, request
    ) -> list[SBAdminCustomAction]:
        return self.process_list_actions(
            request,
            self.get_sbadmin_list_selection_actions(request),
            object_id=getattr(
                getattr(request, "request_data", None), "object_id", None
            ),
        )

    def get_sbadmin_row_actions(self, request) -> list[SBAdminRowAction]:
        return [*(self.sbadmin_row_actions or [])]

    def get_sbadmin_row_actions_processed(self, request) -> list[SBAdminRowAction]:
        return self.process_row_actions(request, self.get_sbadmin_row_actions(request))

    def get_sbadmin_list_selection_actions_grouped(
        self, request
    ) -> dict[str, list[SBAdminCustomAction]]:
        result = {}
        list_selection_actions = self.get_sbadmin_list_selection_actions_processed(
            request
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

    @sbadmin_action(permission="view")
    def action_xlsx_export(self, request, modifier, object_id=None) -> HttpResponse:
        action = self.sbadmin_list_action_class(self, request)
        data = action.get_xlsx_data(request)
        return SBAdminXLSXExportService.create_workbook_http_respone(*data)

    @sbadmin_action(permission="delete")
    def action_bulk_delete(self, request, modifier, object_id=None):
        action = self.sbadmin_list_action_class(self, request)
        if (
            request.request_data.request_method == "POST"
            and request.headers.get("X-TabulatorRequest", None) == "true"
        ):
            return redirect(
                self.get_action_url(
                    "action_bulk_delete", object_id=request.request_data.object_id
                )
                + "?"
                + urllib.parse.urlencode(
                    {
                        BASE_PARAMS_NAME: SBAdminViewService.json_dumps_for_url(
                            action.all_params, request
                        )
                    }
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
        if isinstance(response, TemplateResponse):
            response.context_data.update(self.get_global_context(request))
        return response

    @sbadmin_action(permission="view")
    def action_config(self, request, modifier=None, object_id=None):
        config_id = modifier
        config_id = config_id if config_id != "None" else None

        config_name = request.POST.get(CONFIG_NAME, None)
        if config_name:
            config_name = urllib.parse.unquote(config_name)
        updated_configuration = None
        if request.request_data.request_method == "POST":
            updated_configuration = (
                SBAdminUserConfigurationService.create_or_update_saved_view(
                    request,
                    view_id=self.get_id(),
                    config_id=config_id,
                    config_name=config_name,
                    url_params=request.request_data.request_post.get(URL_PARAMS_NAME),
                )
            )
        if request.request_data.request_method == "DELETE":
            SBAdminUserConfigurationService.delete_saved_view(
                request,
                view_id=self.get_id(),
                config_id=config_id,
            )

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

    @sbadmin_action(permission="view")
    def action_list(
        self,
        request,
        modifier=None,
        object_id=None,
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

    @sbadmin_action(permission="view")
    def action_list_json(
        self, request, modifier, object_id=None, page_size=None
    ) -> JsonResponse:
        action = self.sbadmin_list_action_class(self, request, page_size=page_size)
        data = action.get_json_data()
        notifications_html = render_notifications_if_any(request)
        if notifications_html:
            data[SB_ADMIN_AJAX_NOTIFICATIONS_KEY] = notifications_html
        return JsonResponse(data=data, safe=False)

    def get_sbadmin_list_filter(self, request) -> Iterable | None:
        return self.sbadmin_list_filter

    def get_all_config(self, request) -> dict[str, Any]:
        all_config = {"name": _("All"), "url_params": {}, "default": True}
        list_filter = self.get_sbadmin_list_filter(request) or []
        if not list_filter:
            return all_config
        list_fields = self.get_sbadmin_list_display(request) or []
        base_filter = {}
        name_of_field = (
            lambda field: getattr(field, "filter_field", None)
            or getattr(field, "name", None)
            or field
        )
        for field in list_fields:
            if (
                field in list_filter
                or getattr(field, "name", None) in list_filter
                or getattr(field, "filter_field", None) in list_filter
            ):
                base_filter[name_of_field(field)] = ""

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
                    "url_params": SBAdminViewService.json_dumps_and_replace(url_params),
                    "default": True,
                }
            )
        return views

    def get_config_data(self, request) -> dict[str, list[dict[str, Any]]]:
        current_views = SBAdminUserConfigurationService.get_saved_views(
            request, view_id=self.get_id()
        )
        for view in current_views:
            view["detail_url"] = self.get_config_url(request, view["id"])
        config_views = self.get_base_config(request)
        config_views.extend(current_views)
        return {"current_views": config_views}

    def get_ajax_url(self, request=None) -> str:
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        return self.get_action_url(Action.LIST_JSON.value, object_id=object_id)

    def get_detail_url(self) -> str:
        return self.get_action_url(
            Action.DETAIL.value,
            object_id=OBJECT_ID_PLACEHOLDER,
        )

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
