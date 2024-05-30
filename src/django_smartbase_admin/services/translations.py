from django.conf import settings
from django.db.models import Value, IntegerField, Q, When, Case, FilteredRelation, F
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.engine.const import (
    Action,
    TRANSLATIONS_SELECTED_LANGUAGES,
    DETAIL_STRUCTURE_RIGHT_CLASS,
)
from django_smartbase_admin.utils import to_list


class SBAdminTranslationsService(object):
    parler_technical_fields = ["id", "language_code", "master"]

    @classmethod
    def get_selected_language_codes(cls, request):
        selected_lang_codes = request.session.get(
            TRANSLATIONS_SELECTED_LANGUAGES, {}
        ).get(TRANSLATIONS_SELECTED_LANGUAGES, [cls.get_translation_languages()[0][0]])
        selected_lang_codes = to_list(selected_lang_codes)
        return selected_lang_codes

    @classmethod
    def get_all_languages(cls):
        return settings.LANGUAGES

    @classmethod
    def get_translation_languages(cls):
        return [
            lang
            for lang in SBAdminTranslationsService.get_all_languages()
            if lang[0] != SBAdminTranslationsService.get_main_lang_code()
        ]

    @classmethod
    def get_main_lang_code(cls):
        return settings.LANGUAGE_CODE

    @classmethod
    def get_annotate_name(cls, translation_model, language_code):
        return str(f"{translation_model._meta.db_table}_{language_code}")

    @classmethod
    def annotate_queryset_with_translations_count(
        cls, queryset, model, language_codes_to_annotate
    ):
        annotates = {}
        for translation_model in model._parler_meta.get_all_models():
            for language_code in language_codes_to_annotate:
                annotate_name = cls.get_annotate_name(translation_model, language_code)
                rel_name = model._parler_meta[translation_model].rel_name
                annotates[annotate_name] = FilteredRelation(
                    rel_name,
                    condition=Q(**{f"{rel_name}__language_code": language_code}),
                )
                field_val_bools = None
                translated_fields_dict = (
                    SBAdminTranslationsService.get_translated_fields_for_model(model)
                )
                for model_field in translated_fields_dict.get(translation_model, []):
                    field_val_bool = str(f"{annotate_name}_{model_field.name}_bool")
                    annotates[field_val_bool] = Case(
                        When(
                            Q(**{f"{annotate_name}__{model_field.name}__isnull": False})
                            & ~Q(**{f"{annotate_name}__{model_field.name}": ""}),
                            then=Value(1),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    )
                    if not field_val_bools:
                        field_val_bools = F(field_val_bool)
                    else:
                        field_val_bools += F(field_val_bool)
                annotates[f"{annotate_name}_count"] = field_val_bools
        queryset = queryset.annotate(**annotates)
        return queryset

    @classmethod
    def is_translated_model(cls, model):
        return bool(getattr(model, "_parler_meta", None))

    @classmethod
    def get_translations_key(cls, translation_model):
        return translation_model._meta.db_table

    @classmethod
    def get_translation_view_id(cls, model):
        return f"translations-{model._meta.db_table}"

    @classmethod
    def get_model_translation_list_url(cls, view_id):
        url = reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": view_id,
                "action": Action.LIST.value,
                "modifier": "template",
            },
        )
        return url

    @classmethod
    def get_model_translation_detail_url(cls, view_id, object_id):
        url = reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": view_id,
                "action": Action.DETAIL.value,
                "modifier": "template",
            },
        )
        return f"{url}/{object_id}"

    @classmethod
    def get_translated_fields_for_model(cls, model, visible_fields=None):
        translated_fields = {}
        if model is None or not cls.is_translated_model(model):
            return translated_fields
        for translation_model in model._parler_meta.get_all_models():
            translated_fields[translation_model] = [
                model_field
                for model_field in translation_model._meta.get_fields()
                if model_field.name not in cls.parler_technical_fields
                # if field is in visible fields or visible fields are empty
                and (not visible_fields or model_field.name in visible_fields)
            ]
        return translated_fields

    @classmethod
    def get_field_from_model(cls, model, field):
        return (
            model._parler_meta.get_model_by_field(field)._meta.get_field(field)
            if cls.is_translated_model(model)
            else None
        )

    @classmethod
    def get_translation_fieldset(cls):
        return (
            _("Translations"),
            {
                "classes": [
                    DETAIL_STRUCTURE_RIGHT_CLASS,
                    "translations-status-fieldset",
                ],
                "fields": ["sbadmin_translation_status"],
            },
        )

    @classmethod
    def is_i18n_enabled(cls):
        return len(settings.LANGUAGES) > 1
