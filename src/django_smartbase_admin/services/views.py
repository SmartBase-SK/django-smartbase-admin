import json
import pickle
import urllib
from typing import Any, TYPE_CHECKING
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from django.core.exceptions import PermissionDenied
from django.db.models import Q, FilteredRelation, F
from django.http import Http404, HttpRequest
from django.shortcuts import redirect
from django.urls import reverse, resolve, Resolver404, get_script_prefix
from django.utils.http import url_has_allowed_host_and_scheme

from django_smartbase_admin.engine.const import (
    BASE_PARAMS_NAME,
    FILTER_DATA_NAME,
    FilterVersions,
    ADVANCED_FILTER_DATA_NAME,
    TABLE_PARAMS_SELECTED_FILTER_TYPE,
    TABLE_TAB_ADVANCED_FITLERS,
    SB_ADMIN_BACK_URL,
)
from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.url_params_codec import (
    dumps_for_url,
    loads_from_url,
    parse_changelist_filters,
)
from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

if TYPE_CHECKING:
    from django_smartbase_admin.engine.field import SBAdminField


class SBAdminViewService(object):
    @classmethod
    def is_url_compression_enabled(cls, request=None) -> bool:
        if request is None:
            try:
                request = SBAdminThreadLocalService.get_request()
            except LookupError:
                return True
        configuration = getattr(
            getattr(request, "request_data", None), "configuration", None
        )
        if configuration is None:
            return True
        return getattr(configuration, "enable_url_compression", True)

    @classmethod
    def json_dumps_for_url(cls, data, request=None):
        return dumps_for_url(data, compress=cls.is_url_compression_enabled(request))

    @classmethod
    def json_loads_from_url(cls, value: str | None) -> dict:
        return loads_from_url(value)

    @classmethod
    def parse_changelist_filters(cls, raw_filters: str) -> dict:
        return parse_changelist_filters(raw_filters)

    @classmethod
    def json_dumps_and_replace(cls, data):
        return json.dumps(data, separators=(",", ":"), cls=SBAdminJSONEncoder)

    @classmethod
    def build_list_url(cls, view_id, url_params, request=None):
        params = {
            BASE_PARAMS_NAME: cls.json_dumps_for_url({view_id: url_params}, request)
        }
        return urllib.parse.urlencode(params)

    @classmethod
    def process_url_params(cls, view_id, url_params, filter_version):
        url_params = url_params or {}
        filter_data = SBAdminViewService.process_filter_data_url(
            view_id=view_id,
            filter_data=url_params.get(FILTER_DATA_NAME, {}),
            filter_version=filter_version,
        )
        url_params_processed = {**url_params}
        if filter_data:
            url_params_processed[FILTER_DATA_NAME] = filter_data
        return url_params_processed

    @classmethod
    def process_filter_data_url(cls, view_id, filter_data, filter_version):
        if filter_version == FilterVersions.FILTERS_VERSION_2:
            filter_data_processed = []
            for key, value in filter_data.items():
                filter_value = {
                    "id": f"{view_id}-{key}",
                    "field": key,
                    "type": "string",
                    "input": "text",
                    "operator": "contains",
                }
                filter_value.update(value)
                filter_data_processed.append(filter_value)
            return filter_data_processed
        else:
            filter_data_processed = {}
            for filter_key, filter_value in filter_data.items():
                if isinstance(filter_value, str):
                    filter_data_processed[filter_key] = filter_value
                else:
                    filter_data_processed[filter_key] = cls.json_dumps_and_replace(
                        filter_value
                    )
            return filter_data_processed

    @classmethod
    def build_list_params_url(
        cls, view_id, filter_data=None, filter_version=None, request=None
    ):
        if filter_version == FilterVersions.FILTERS_VERSION_2:
            filter_dict = {
                ADVANCED_FILTER_DATA_NAME: {
                    "condition": "AND",
                    "rules": [],
                    "valid": True,
                },
                FILTER_DATA_NAME: {
                    TABLE_PARAMS_SELECTED_FILTER_TYPE: TABLE_TAB_ADVANCED_FITLERS
                },
            }
            filter_dict[ADVANCED_FILTER_DATA_NAME]["rules"].extend(
                cls.process_filter_data_url(view_id, filter_data, filter_version)
            )
            params = {
                BASE_PARAMS_NAME: cls.json_dumps_for_url(
                    {view_id: filter_dict}, request
                )
            }
            return urllib.parse.urlencode(params)
        filter_data = filter_data or {}
        view_params = {
            FILTER_DATA_NAME: cls.process_filter_data_url(
                view_id, filter_data, filter_version
            )
        }
        return cls.build_list_url(view_id, view_params, request)

    @classmethod
    def get_pk_field_for_model(cls, model):
        return model._meta.pk

    @classmethod
    def replace_legacy_admin_access_in_response(cls, response):
        is_rendered = getattr(response, "is_rendered", None)
        if is_rendered is not None and not is_rendered:
            response.render()
        response.content = (
            response.content.decode()
            .replace(
                f'href="{reverse("admin:index")}',
                f'href="{reverse("sb_admin:index")}',
            )
            .encode()
        )
        return response

    @classmethod
    def get_detail_fields(cls, fields):
        return [field.name for field in fields if field.detail_visible]

    @classmethod
    def get_model_path(cls, model):
        return f"{model._meta.app_label}_{model._meta.model_name}"

    @classmethod
    def delegate_to_action(cls, request, *args, **kwargs):
        request_data = SBAdminViewRequestData.from_request_and_kwargs(request, **kwargs)
        request_data.selected_view.init_view_dynamic(request, request_data, **kwargs)
        if request_data.selected_view and not request_data.action:
            return redirect(request_data.selected_view.get_menu_view_url(request))

        view = request_data.selected_view
        action_name = request_data.action

        action_function = getattr(view, action_name, None)
        if not action_function or not getattr(
            action_function, "_is_sbadmin_action", False
        ):
            raise Http404

        action_attrs = getattr(action_function, "_sbadmin_action_attrs", {}) or {}
        action_obj = SBAdminCustomAction(
            title=action_name,
            view=view,
            action_id=action_name,
            action_modifier=request_data.modifier,
            permission=action_attrs.get("permission"),
        )
        if not view.has_permission_for_action(request, action_obj):
            raise PermissionDenied

        return action_function(
            request,
            request_data.modifier,
            request_data.object_id,
        )

    @classmethod
    def apply_global_filter_to_queryset(
        cls, qs, request, request_data, global_filter_data_map
    ):
        return request_data.configuration.apply_global_filter_to_queryset(
            qs, request, request_data, global_filter_data_map
        )

    @classmethod
    def has_permission(cls, request, view=None, model=None, obj=None, permission=None):
        configuration = request.request_data.configuration
        is_mcp_readonly_permission = getattr(
            configuration, "is_mcp_readonly_permission", None
        )
        if (
            callable(is_mcp_readonly_permission)
            and is_mcp_readonly_permission(request, permission) is True
        ):
            return False
        return configuration.has_permission(
            request, request.request_data, view, model, obj, permission
        )

    @classmethod
    def get_restricted_queryset(
        cls,
        model,
        request,
        request_data,
        global_filter=True,
        global_filter_data_map=None,
        qs=None,
    ):
        qs = qs or model.objects.all()
        if global_filter:
            qs = cls.apply_global_filter_to_queryset(
                qs, request, request_data, global_filter_data_map
            )
        qs = request_data.configuration.restrict_queryset(
            qs=qs,
            model=model,
            request=request,
            request_data=request_data,
            global_filter=global_filter,
            global_filter_data_map=global_filter_data_map,
        )
        return qs

    @classmethod
    def filter_value_empty(cls, filter_value: Any) -> bool:
        return (
            filter_value is None
            or filter_value == ""
            or (isinstance(filter_value, list) and len(filter_value) == 0)
        )

    @classmethod
    def get_cache_key_for_user(cls, request_data) -> str:
        return (
            f"{request_data.user.id}_{pickle.dumps(request_data.object_id)}"
            f"_{pickle.dumps(request_data.global_filter)}"
            f"_{pickle.dumps(request_data.request_get)}"
            f"_{pickle.dumps(request_data.request_post)}"
        )

    @classmethod
    def get_filter_fields_and_values_from_request(
        cls,
        request,
        available_filters: list["SBAdminField"],
        filter_data: dict[str, Any],
    ) -> dict["SBAdminField", Any]:
        filter_fields_and_value = {}
        for field in available_filters:
            filter_value = filter_data.get(field.filter_field, None)
            if filter_value is not None:
                try:
                    filter_value = json.loads(filter_value)
                except Exception:
                    pass
            if not cls.filter_value_empty(filter_value):
                filter_fields_and_value[field] = filter_value
        return filter_fields_and_value

    @classmethod
    def get_filter_from_request(cls, request, available_filters, filter_data):
        filter_fields_and_value = cls.get_filter_fields_and_values_from_request(
            request, available_filters, filter_data
        )
        filter_q = Q()
        for field, filter_value in filter_fields_and_value.items():
            filter_widget_q = field.filter_widget.get_filter_query_for_value(
                request, filter_value
            )
            filter_q &= filter_widget_q
        return filter_q

    @classmethod
    def get_annotates(cls, model, values, fields):
        field_annotates = {}
        lang_annotates = {}
        visible_fields = []
        values_set = set(values)
        for field in fields:
            if field.field in values_set:
                if field.view_method:
                    visible_fields.append(field.filter_field)
                else:
                    visible_fields.append(field.field)
                field_annotates.update(field.get_field_annotates(values))
                continue
            # Parent column is hidden, but its ``supporting_annotates``
            # keys may still appear in ``values`` because another
            # column's formatter needs them or the admin lists them in
            # ``sbadmin_list_display_data``. Emit just those entries
            # so ``.values(...)`` can resolve them — the parent
            # column itself is not rendered.
            if field.supporting_annotates:
                for key, value in field.supporting_annotates.items():
                    if key in values_set:
                        field_annotates[key] = (
                            value.clone()
                            if isinstance(value, FilteredRelation)
                            else value
                        )
        main_language_code = SBAdminTranslationsService.get_main_lang_code()
        for (
            translation_model,
            translated_fields,
        ) in SBAdminTranslationsService.get_translated_fields_for_model(
            model, visible_fields=visible_fields
        ).items():
            annotate_name = f"{SBAdminTranslationsService.get_translations_key(translation_model)}_{main_language_code}"
            lang_annotates[annotate_name] = FilteredRelation(
                model._parler_meta[translation_model].rel_name,
                condition=Q(translations__language_code=main_language_code),
            )
            for model_field in translated_fields:
                lang_annotates[model_field.name] = F(
                    f"{annotate_name}__{model_field.name}"
                )
        return {**lang_annotates, **field_annotates}

    @classmethod
    def _get_back_url_param(cls, request: HttpRequest) -> str | None:
        if request.method == "POST":
            value = request.POST.get(SB_ADMIN_BACK_URL)
            if value:
                return value
        return request.GET.get(SB_ADMIN_BACK_URL) or None

    @classmethod
    def validate_back_url(
        cls, request: HttpRequest, url: str | None, *, current_path: str | None = None
    ) -> bool:
        """A ``back_url`` is valid only if it is a same-host SBAdmin URL.

        Guards against open redirects (external host / scheme) and self-loops.
        """
        if not url:
            return False
        if not url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return False
        path = urlsplit(url).path
        if current_path and path == current_path:
            return False
        script_prefix = get_script_prefix()
        resolve_path = path
        if script_prefix != "/" and resolve_path.startswith(script_prefix):
            resolve_path = "/" + resolve_path[len(script_prefix) :]
        try:
            match = resolve(resolve_path)
        except Resolver404:
            return False
        return match.namespace == "sb_admin"

    @classmethod
    def resolve_back_url(
        cls,
        request: HttpRequest,
        default_url: str,
        *,
        current_path: str | None = None,
    ) -> str:
        """Best back URL, in priority order: ``POST[back_url]`` (hidden field),
        ``GET[back_url]`` (query param), then ``default_url``."""
        candidate = cls._get_back_url_param(request)
        if cls.validate_back_url(request, candidate, current_path=current_path):
            return candidate
        return default_url

    @classmethod
    def append_back_url(cls, target_url: str, back_url: str | None) -> str:
        """Add/replace ``back_url`` on ``target_url`` preserving other params."""
        if not back_url:
            return target_url
        parts = urlsplit(target_url)
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != SB_ADMIN_BACK_URL
        ]
        query.append((SB_ADMIN_BACK_URL, back_url))
        return urlunsplit(parts._replace(query=urlencode(query)))

    @classmethod
    def url_with_current_back_url(cls, request: HttpRequest, target_url: str) -> str:
        """Point an outgoing link at ``target_url`` with a ``back_url`` back to
        the current page (so Save/Back on the target returns here)."""
        return cls.append_back_url(target_url, request.get_full_path())

    @classmethod
    def keep_back_url(cls, request: HttpRequest, url: str) -> str:
        """Carry the request's existing ``back_url`` onto ``url`` (redirects)."""
        return cls.append_back_url(url, cls._get_back_url_param(request))
