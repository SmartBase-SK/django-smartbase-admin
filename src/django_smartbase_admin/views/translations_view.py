from collections import defaultdict

from django import forms
from django.apps import apps
from django.contrib import messages
from django.db.models import Case, When, F, Value, CharField
from django.db.models.functions import Concat
from django.forms import modelform_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.admin.admin_base import SBAdminInlineAndAdminCommon
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import (
    TRANSLATION_MODEL_KEY,
    Action,
    OBJECT_ID_PLACEHOLDER,
    TRANSLATIONS_SELECTED_LANGUAGES,
)
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import RadioChoiceFilterWidget
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.utils import is_htmx_request, querydict_to_dict
from urllib.parse import quote as urlquote


class ModelTranslationView(SBAdminView, SBAdminBaseListView):
    translated_fields = None
    list_template_name = "sb_admin/actions/translations-list.html"
    FORM_BASE_ID = "translation-form-"
    TRANSLATION_NOT_TRANSLATED = 0
    TRANSLATION_INCOMPLETE = 1
    TRANSLATION_TRANSLATED = 2
    TRANSLATION_STATES = [
        (TRANSLATION_NOT_TRANSLATED, _("Not Translated")),
        (TRANSLATION_INCOMPLETE, _("Incomplete")),
        (TRANSLATION_TRANSLATED, _("Translated")),
    ]

    def get_sbadmin_list_view_config(self, request):
        result = []
        translated_fields_dict = self.get_translated_fields()
        for translation_model, translated_fields in translated_fields_dict.items():
            main_lang_annotate_name = self.get_annotate_name(
                translation_model, SBAdminTranslationsService.get_main_lang_code()
            )
            for language_code in self.get_display_language_codes(
                request, include_main=False
            ):
                annotate_name = self.get_annotate_name(translation_model, language_code)
                result.extend(
                    [
                        {
                            "name": _("Translated"),
                            "url_params": {
                                "filterData": {
                                    f"{annotate_name}_status": str(
                                        self.TRANSLATION_TRANSLATED
                                    )
                                }
                            },
                        },
                        {
                            "name": _("Incomplete"),
                            "url_params": {
                                "filterData": {
                                    f"{annotate_name}_status": str(
                                        self.TRANSLATION_INCOMPLETE
                                    )
                                }
                            },
                        },
                        {
                            "name": _("Not Translated"),
                            "url_params": {
                                "filterData": {
                                    f"{annotate_name}_status": str(
                                        self.TRANSLATION_NOT_TRANSLATED
                                    )
                                }
                            },
                        },
                    ]
                )
        return result

    def get_menu_view_url(self, request=None):
        return super().get_menu_view_url(request)

    def get_annotate_name(self, translation_model, language_code):
        return SBAdminTranslationsService.get_annotate_name(
            translation_model, language_code
        )

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        qs = SBAdminTranslationsService.annotate_queryset_with_translations_count(
            qs, self.model, self.get_display_language_codes(request)
        )
        return qs

    def get_context_data(self, request):
        context = {}
        selected_lang = next(iter(self.get_selected_language_codes(request)), None)
        context["languages_form"] = LangForm(
            data={TRANSLATIONS_SELECTED_LANGUAGES: selected_lang}
        )
        context["flag_url"] = f"sb_admin/images/flags/{selected_lang}.png"
        context["translations_selected_key"] = TRANSLATIONS_SELECTED_LANGUAGES
        return context

    def get_selected_language_codes(self, request):
        return SBAdminTranslationsService.get_selected_language_codes(request)

    def get_display_language_codes(self, request, include_main=True):
        lang_codes = (
            [SBAdminTranslationsService.get_main_lang_code()] if include_main else []
        )
        selected_lang_codes = self.get_selected_language_codes(request)
        lang_codes.extend(selected_lang_codes)
        return lang_codes

    def init_fields_cache(self, fields_source=None, configuration=None, force=False):
        return

    def get_field_map(self, request):
        fields = []
        translated_fields_dict = self.get_translated_fields()
        for translation_model, translated_fields in translated_fields_dict.items():
            main_lang_annotate_name = self.get_annotate_name(
                translation_model, SBAdminTranslationsService.get_main_lang_code()
            )

            for model_field in translated_fields:
                if not self.fields or model_field.name in self.fields:
                    field = self.auto_create_field_from_model_field(model_field)
                    field.field = f"{main_lang_annotate_name}__{model_field.name}"
                    fields.append(field)

        for translation_model, translated_fields in translated_fields_dict.items():
            main_lang_annotate_name = self.get_annotate_name(
                translation_model, SBAdminTranslationsService.get_main_lang_code()
            )
            for language_code in self.get_display_language_codes(
                request, include_main=False
            ):
                annotate_name = self.get_annotate_name(translation_model, language_code)
                field = SBAdminField(
                    title=_("Status"),
                    name=f"{annotate_name}_status",
                    formatter="html",
                    filter_widget=RadioChoiceFilterWidget(
                        choices=self.TRANSLATION_STATES,
                    ),
                    python_formatter=self.format_translation_status,
                    annotate=Case(
                        When(
                            **{
                                f"{annotate_name}_count": F(
                                    f"{main_lang_annotate_name}_count"
                                ),
                                "then": Value(self.TRANSLATION_TRANSLATED),
                            }
                        ),
                        When(
                            **{
                                f"{annotate_name}_count": 0,
                                "then": Value(self.TRANSLATION_NOT_TRANSLATED),
                            }
                        ),
                        default=Value(self.TRANSLATION_INCOMPLETE),
                    ),
                )
                fields.append(field)

                field = SBAdminField(
                    title=_("Translated"),
                    name=f"{annotate_name}_count",
                    formatter="html",
                    annotate=Concat(
                        F(f"{annotate_name}_count"),
                        Value(str(_(" of "))),
                        F(f"{main_lang_annotate_name}_count"),
                        output_field=CharField(),
                    ),
                )
                fields.append(field)

        field_map = {}
        list_display = []
        for field in fields:
            field.init_field_static(self, request.request_data.configuration)
            field_map[field.name] = field
            list_display.append(field.name)
        self.list_display = list_display
        return field_map

    def get_translation_models(self):
        return SBAdminTranslationsService.get_translated_fields_for_model(
            self.model
        ).keys()

    def format_translation_status(self, object_id, value):
        if value == self.TRANSLATION_NOT_TRANSLATED:
            return f'<span class="badge badge-simple badge-neutral"><svg class="w-16 h-16 mr-4 text-invisible"><use xlink:href="#Add-one"></use></svg>{_("Not Translated")}</span>'
        if value == self.TRANSLATION_INCOMPLETE:
            return f'<span class="badge badge-simple badge-warning"><svg class="w-16 h-16 mr-4 text-warning"><use xlink:href="#Attention"></use></svg>{_("Incomplete")}</span>'
        if value == self.TRANSLATION_TRANSLATED:
            return f'<span class="badge badge-simple badge-positive"><svg class="w-16 h-16 mr-4 text-success"><use xlink:href="#Check"></use></svg>{_("Translated")}</span>'

    def get_translated_fields(self):
        return SBAdminTranslationsService.get_translated_fields_for_model(self.model)

    def handle_language_choice_change(self, request):
        if (
            request.request_data.request_method == "POST"
            and is_htmx_request(request.request_data.request_meta)
            and request.request_data.request_post.get(
                TRANSLATIONS_SELECTED_LANGUAGES, None
            )
        ):
            request.request_data.session[TRANSLATIONS_SELECTED_LANGUAGES] = (
                querydict_to_dict(request.request_data.request_post)
            )
            response = HttpResponse()
            redirect_url = request.request_data.request_meta.get("HTTP_REFERER", "/")
            if request.request_data.object_id:
                redirect_url = (
                    SBAdminTranslationsService.get_model_translation_detail_url(
                        self.get_id(), request.request_data.object_id
                    )
                )
            response["HX-Redirect"] = redirect_url
            return response
        return None

    def list(self, request, modifier):
        language_choice_change_response = self.handle_language_choice_change(request)
        if language_choice_change_response:
            return language_choice_change_response
        self.init_fields_cache(configuration=request.request_data.configuration)
        action = SBAdminListAction(self, request)
        data = action.get_template_data()
        context = self.get_context_data(request)
        context.update(self.get_global_context(request))
        context["content_context"] = data
        context.update(
            {
                "list_title": f"{_('Translations')} / {self.model._meta.verbose_name_plural}",
            }
        )
        return TemplateResponse(
            request,
            self.list_template_name,
            context=context,
        )

    def save_translation(self, request, form):
        translation_obj = form.save(commit=False)
        translation_obj.master_id = request.request_data.object_id
        translation_obj.save()
        return translation_obj

    def detail(self, request, modifier):
        main_language_code = SBAdminTranslationsService.get_main_lang_code()
        language_choice_change_response = self.handle_language_choice_change(request)
        if language_choice_change_response:
            return language_choice_change_response
        translation_models = self.get_translation_models()
        translated_field_names = {
            SBAdminTranslationsService.get_translations_key(translation_model): [
                model_field.name for model_field in model_fields
            ]
            for translation_model, model_fields in self.get_translated_fields().items()
        }
        translation_forms = defaultdict(list)
        for translated_model in translation_models:
            translation_form_widgets = {
                "id": forms.HiddenInput,
                "language_code": forms.HiddenInput,
            }

            translation_fields = [
                "id",
                "language_code",
                *translated_field_names[
                    SBAdminTranslationsService.get_translations_key(translated_model)
                ],
            ]

            translation_form_class = modelform_factory(
                translated_model,
                fields=translation_fields,
                widgets=translation_form_widgets,
            )

            for field_name, field in translation_form_class.base_fields.items():
                if translation_form_widgets.get(field_name):
                    continue

                widget = SBAdminInlineAndAdminCommon.formfield_widgets.get(
                    field.__class__
                )
                if not widget:
                    continue
                choices = getattr(field, "choices", None)
                if choices:
                    field.widget = widget(form_field=field, choices=choices)
                    continue
                field.widget = widget(form_field=field)

            for language_code in self.get_display_language_codes(
                request, include_main=True
            ):
                auto_id = f"id_{language_code}_%s"
                translation_instance = (
                    SBAdminViewService.get_restricted_queryset(
                        translated_model,
                        request,
                        request.request_data,
                    )
                    .filter(
                        master=request.request_data.object_id,
                        language_code=language_code,
                    )
                    .first()
                )
                if request.request_data.request_post.get(
                    "language_code"
                ) == language_code and request.request_data.request_post.get(
                    TRANSLATION_MODEL_KEY
                ) == SBAdminTranslationsService.get_translations_key(
                    translated_model
                ):
                    translation_form = translation_form_class(
                        data=request.request_data.request_post,
                        instance=translation_instance,
                        auto_id=auto_id,
                    )
                    if translation_form.is_valid():
                        translation_obj = self.save_translation(
                            request, translation_form
                        )
                        msg_dict = {
                            "name": f"{_('Translations')} / {self.model._meta.verbose_name_plural}",
                            "obj": format_html(
                                '<a href="{}">{}</a>',
                                urlquote(request.path),
                                f"{translation_obj.master} ({translation_obj})",
                            ),
                        }
                        return self.get_detail_change_response(request, msg_dict)
                elif translation_instance:
                    translation_form = translation_form_class(
                        instance=translation_instance, auto_id=auto_id
                    )
                else:
                    translation_form = translation_form_class(
                        initial={"language_code": language_code}, auto_id=auto_id
                    )
                setattr(
                    translation_form,
                    TRANSLATION_MODEL_KEY,
                    SBAdminTranslationsService.get_translations_key(translated_model),
                )

                for field_name, field in translation_form.fields.items():
                    if language_code == main_language_code:
                        field.widget.attrs["readonly"] = True
                    field.widget.attrs["form"] = f"{self.FORM_BASE_ID}{language_code}"

                translation_forms[language_code].append(translation_form)

        context = self.get_global_context(request)
        context.update(
            {
                "translation_forms": dict(translation_forms),
                "title": f"{_('Translations')} / {self.model._meta.verbose_name}",
                "TRANSLATION_MODEL_KEY": TRANSLATION_MODEL_KEY,
                "FORM_BASE_ID": self.FORM_BASE_ID,
                "back_url": self.get_back_url(request),
                "main_language_code": main_language_code,
                **self.get_context_data(request),
            }
        )
        return TemplateResponse(
            request,
            "sb_admin/actions/translations-detail.html",
            context=context,
        )

    def get_detail_url(self):
        return SBAdminTranslationsService.get_model_translation_detail_url(
            self.get_id(), OBJECT_ID_PLACEHOLDER
        )


class LangForm(forms.Form):
    translation_selected_languages = forms.ChoiceField(
        choices=SBAdminTranslationsService.get_translation_languages()
    )


class SBAdminTranslationsView(SBAdminView):
    label = _("Translations")
    menu_action = "translations"
    view_id = "translations"
    sub_views_menu = None

    def __init__(
        self,
        translations_definition=None,
        model=None,
        label=None,
        title=None,
        icon=None,
        description=None,
        view_id=None,
        menu_action=None,
        fields=None,
        list_display=None,
        list_per_page=None,
        ordering=None,
        list_template_name=None,
        global_filter_data_map=None,
        sub_views=None,
    ) -> None:
        super().__init__(
            model,
            label,
            title,
            icon,
            description,
            view_id,
            menu_action,
            fields,
            list_display,
            list_per_page,
            ordering,
            list_template_name,
            global_filter_data_map,
            sub_views,
        )
        self.translations_definition = translations_definition

    def translations(self, request, modifier):
        context = self.get_global_context(request)
        context.update({"sub_views": self.sub_views})
        return TemplateResponse(
            request,
            "sb_admin/actions/translations.html",
            context=context,
        )

    def get_sub_views(self, configuration):
        self.sub_views = []
        self.sub_views_menu = []
        translations_definition = self.translations_definition or []

        for translation_definition in translations_definition:
            model_path = translation_definition["model_path"].split(".")
            app_label = ".".join(model_path[:-1])
            model_name = model_path[-1]
            model = apps.get_model(app_label, model_name)
            translations_rel = SBAdminTranslationsService.is_translated_model(model)
            if not model._meta.proxy and translations_rel:
                view_class = (
                    translation_definition.get("view_class") or ModelTranslationView
                )
                view_class_params = {
                    "view_id": SBAdminTranslationsService.get_translation_view_id(
                        model
                    ),
                    "label": model._meta.verbose_name_plural,
                    "model": model,
                    "description": translation_definition.get("description"),
                    "icon": translation_definition.get("icon"),
                }
                if translation_definition.get("fields"):
                    view_class_params["fields"] = translation_definition.get("fields")
                view = view_class(**view_class_params)
                self.sub_views.append(view)
        return self.sub_views
