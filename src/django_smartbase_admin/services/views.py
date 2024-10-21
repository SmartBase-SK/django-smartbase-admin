import json
import pickle
import urllib

from django.conf import settings
from django.db.models import Q, FilteredRelation, F, Value, CharField
from django.shortcuts import redirect
from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

from django_smartbase_admin.engine.const import (
    BASE_PARAMS_NAME,
    FILTER_DATA_NAME,
    FilterVersions,
    ADVANCED_FILTER_DATA_NAME,
    TABLE_PARAMS_SELECTED_FILTER_TYPE,
    TABLE_TAB_ADVANCED_FITLERS,
)
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.translations import SBAdminTranslationsService


class SBAdminViewService(object):
    @classmethod
    def json_dumps_for_url(cls, data):
        return json.dumps(data, separators=(",", ":"), cls=SBAdminJSONEncoder)

    @classmethod
    def json_dumps_and_replace(cls, data):
        return cls.json_dumps_for_url(data)

    @classmethod
    def build_list_url(cls, view_id, url_params):
        params = {view_id: url_params}
        return f"{BASE_PARAMS_NAME}={cls.json_dumps_for_url(params)}"

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
                filter_data_processed[filter_key] = cls.json_dumps_and_replace(
                    filter_value
                )
        return filter_data_processed

    @classmethod
    def build_list_params_url(cls, view_id, filter_data=None, filter_version=None):
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
            params = {BASE_PARAMS_NAME: cls.json_dumps_for_url({view_id: filter_dict})}
            return urllib.parse.urlencode(params)
        filter_data = filter_data or {}
        view_params = {
            FILTER_DATA_NAME: cls.process_filter_data_url(
                view_id, filter_data, filter_version
            )
        }
        return cls.build_list_url(view_id, view_params)

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
                f'href="/{settings.ADMIN_PATH}', f'href="/{settings.SB_ADMIN_PATH}'
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
        return getattr(request_data.selected_view, request_data.action)(
            request, request_data.modifier
        )

    @classmethod
    def apply_global_filter_to_queryset(
        cls, qs, request, request_data, global_filter_data_map
    ):
        return request_data.configuration.apply_global_filter_to_queryset(
            qs, request, request_data, global_filter_data_map
        )

    @classmethod
    def has_permission(cls, request, view, model=None, obj=None, permission=None):
        return request.request_data.configuration.has_permission(
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
    ):
        qs = model.objects.all()
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
    def filter_value_empty(cls, filter_value):
        return (
            filter_value is None
            or filter_value == ""
            or (isinstance(filter_value, list) and len(filter_value) == 0)
        )

    @classmethod
    def get_cache_key_for_user(cls, request_data):
        return f"{request_data.user.id}_{pickle.dumps(request_data.global_filter)}_{pickle.dumps(request_data.request_get)}_{pickle.dumps(request_data.request_post)}"

    @classmethod
    def get_filter_fields_and_values_from_request(
        cls, request, available_filters, filter_data
    ):
        filter_fields_and_value = {}
        for field in available_filters:
            filter_value = filter_data.get(field.filter_field, None)
            if filter_value is not None:
                try:
                    filter_value = json.loads(filter_value)
                except:
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
        for field in fields:
            if field.field in values:
                if field.view_method:
                    visible_fields.append(field.filter_field)
                else:
                    visible_fields.append(field.field)
                field_annotates.update(field.get_field_annotates(values))
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
