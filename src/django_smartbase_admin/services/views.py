import json
import pickle

from django.db.models import Q, FilteredRelation, F, Value, CharField
from django.shortcuts import redirect

from django_smartbase_admin.engine.const import BASE_PARAMS_NAME, FILTER_DATA_NAME
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.utils import to_list


class SBAdminViewService(object):
    @classmethod
    def json_dumps_for_url(cls, data):
        return json.dumps(data, separators=(",", ":"))

    @classmethod
    def json_dumps_and_replace(cls, data):
        return cls.json_dumps_for_url(data).replace('"', '\\"')

    @classmethod
    def build_list_url(cls, view_id, url_params):
        params = {view_id: url_params}
        return f"{BASE_PARAMS_NAME}={cls.json_dumps_for_url(params)}"

    @classmethod
    def build_list_params_url(cls, view_id, filter_data=None):
        filter_data = filter_data or {}
        filter_data_processed = {}
        for filter_key, filter_value in filter_data.items():
            filter_data_processed[filter_key] = cls.json_dumps_and_replace(filter_value)
        view_params = {FILTER_DATA_NAME: filter_data_processed}
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
            .replace('href="/admin/', 'href="/sb-admin/')
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
        supporting_annotates = {}
        visible_fields = []
        for field in fields:
            if field.field in values:
                if field.view_method:
                    visible_fields.append(field.filter_field)
                else:
                    visible_fields.append(field.field)
                if field.annotate:
                    field_annotates[field.field] = field.annotate
                if field.annotate_function:
                    function_result = field.annotate_function(field, values)
                    if function_result:
                        field_annotates[field.field] = function_result
                    else:
                        field_annotates[field.field] = Value(
                            None, output_field=CharField()
                        )
                if field.supporting_annotates:
                    supporting_annotates.update(field.supporting_annotates)
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
        return {**lang_annotates, **supporting_annotates, **field_annotates}
