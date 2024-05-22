import json
import urllib.parse

from ckeditor.fields import RichTextFormField
from ckeditor_uploader.fields import RichTextUploadingFormField
from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import AdminTextareaWidget
from django.contrib.auth.forms import UsernameField, ReadOnlyPasswordHashWidget
from django.contrib.postgres.forms import SimpleArrayField
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.forms import HiddenInput
from django.forms.models import ModelFormMetaclass
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_admin_inline_paginator.admin import TabularInlinePaginated
from filer.fields.image import AdminImageFormField
from nested_admin.nested import (
    NestedModelAdmin,
    NestedTabularInline,
    NestedGenericTabularInline,
    NestedStackedInline,
    NestedGenericStackedInline,
)

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.utils import FormFieldsetMixin

parler_enabled = None
try:
    from parler.forms import (
        TranslatableModelForm,
        TranslatableModelFormMetaclass,
        _get_mro_attribute,
        TranslatedField,
        _get_model_form_field,
        BaseTranslatableModelForm,
    )

    parler_enabled = True
except ImportError:
    pass

from django_smartbase_admin.admin.widgets import (
    SBAdminTextInputWidget,
    SBAdminTextareaWidget,
    SBAdminURLFieldWidget,
    SBAdminEmailInputWidget,
    SBAdminNumberWidget,
    SBAdminCKEditorWidget,
    SBAdminSelectWidget,
    SBAdminDateWidget,
    SBAdminSplitDateTimeWidget,
    SBAdminTimeWidget,
    SBAdminDateTimeWidget,
    SBAdminAutocompleteWidget,
    SBAdminFileWidget,
    SBAdminToggleWidget,
    SBAdminNullBooleanSelectWidget,
    SBAdminArrayWidget,
    SBAdminImageWidget,
    SBAdminPasswordInputWidget,
    SBAdminReadOnlyPasswordHashWidget,
    SBAdminHiddenWidget,
)
from django_smartbase_admin.engine.admin_base_view import (
    SBAdminBaseListView,
    SBAdminBaseView,
    SBAdminBaseQuerysetMixin,
)
from django_smartbase_admin.engine.const import (
    OBJECT_ID_PLACEHOLDER,
    TRANSLATIONS_SELECTED_LANGUAGES,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.views import SBAdminViewService


class SBAdminFormFieldWidgetsMixin:
    formfield_widgets = {
        forms.DateTimeField: SBAdminDateTimeWidget,
        forms.SplitDateTimeField: SBAdminSplitDateTimeWidget,
        forms.DateField: SBAdminDateWidget,
        forms.TimeField: SBAdminTimeWidget,
        forms.Textarea: SBAdminTextareaWidget,
        forms.URLField: SBAdminURLFieldWidget,
        forms.IntegerField: SBAdminNumberWidget,
        forms.FloatField: SBAdminNumberWidget,
        forms.CharField: SBAdminTextInputWidget,
        UsernameField: SBAdminTextInputWidget,
        forms.JSONField: SBAdminTextareaWidget,
        forms.ImageField: SBAdminFileWidget,
        forms.FileField: SBAdminFileWidget,
        forms.EmailField: SBAdminEmailInputWidget,
        forms.UUIDField: SBAdminTextInputWidget,
        forms.DecimalField: SBAdminNumberWidget,
        forms.BooleanField: SBAdminToggleWidget,
        forms.SlugField: SBAdminTextInputWidget,
        RichTextFormField: SBAdminCKEditorWidget,
        RichTextUploadingFormField: SBAdminCKEditorWidget,
        forms.ChoiceField: SBAdminSelectWidget,
        forms.TypedChoiceField: SBAdminSelectWidget,
        forms.NullBooleanField: SBAdminNullBooleanSelectWidget,
        SimpleArrayField: SBAdminArrayWidget,
        AdminImageFormField: SBAdminImageWidget,
        ReadOnlyPasswordHashWidget: SBAdminReadOnlyPasswordHashWidget,
        forms.HiddenInput: SBAdminHiddenWidget,
    }

    django_widget_to_widget = {
        forms.PasswordInput: SBAdminPasswordInputWidget,
        AdminTextareaWidget: SBAdminTextareaWidget,
    }

    def get_form_field_widget_class(self, form_field, db_field, request):
        default_widget_class = self.formfield_widgets.get(form_field.__class__)
        return request.request_data.configuration.get_form_field_widget_class(
            self, request, form_field, db_field, default_widget_class
        )

    def get_autocomplete_widget(
        self, request, form_field, db_field, model, multiselect=False
    ):
        return request.request_data.configuration.get_autocomplete_widget(
            self, request, form_field, db_field, model, multiselect
        )

    def assign_widget_to_form_field(self, form_field, db_field=None, request=None):
        form_field.view = self
        if getattr(form_field.widget, "sb_admin_widget", None):
            if not form_field.widget.form_field:
                form_field.widget.form_field = form_field
            return form_field

        widget = self.django_widget_to_widget.get(form_field.widget.__class__)
        if not widget:
            widget = self.get_form_field_widget_class(form_field, db_field, request)

        if not widget:
            return form_field
        choices = getattr(form_field, "choices", None)
        if choices:
            form_field.widget = widget(form_field=form_field, choices=choices)
            return form_field
        widget_attrs = form_field.widget.attrs
        widget_attrs.pop(
            "class", None
        )  # remove origin classes to prevent override our custom widget class
        form_field.widget = widget(form_field=form_field, attrs=widget_attrs)
        return form_field

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        form_field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if form_field:
            form_field.view = self
            form_field_widget_class = self.get_form_field_widget_class(
                form_field, db_field, request
            )
            if form_field_widget_class:
                form_field_widget_instance = form_field_widget_class(
                    form_field=form_field
                )
            else:
                form_field_widget_instance = self.get_autocomplete_widget(
                    request,
                    form_field,
                    db_field,
                    db_field.target_field.model,
                    multiselect=False,
                )
            form_field_widget_instance.init_widget_dynamic(
                self, form_field, db_field.name, self, request
            )
            form_field.widget = form_field_widget_instance
        return form_field

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        form_field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if form_field:
            form_field.view = self
            form_field_widget_class = self.get_form_field_widget_class(
                form_field, db_field, request
            )
            if form_field_widget_class:
                form_field_widget_instance = form_field_widget_class(
                    form_field=form_field
                )
            else:
                form_field_widget_instance = self.get_autocomplete_widget(
                    request,
                    form_field,
                    db_field.target_field.model,
                    multiselect=True,
                )
            form_field_widget_instance.init_widget_dynamic(
                self, form_field, db_field.name, self, request
            )
            form_field.widget = form_field_widget_instance
            if form_field.help_text == _(
                "Hold down “Control”, or “Command” on a Mac, to select more than one."
            ):
                form_field.help_text = ""
        return form_field

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if isinstance(db_field, models.ForeignKey):
            form_field = self.formfield_for_foreignkey(db_field, request, **kwargs)
            return form_field
        if isinstance(db_field, models.ManyToManyField):
            form_field = self.formfield_for_manytomany(db_field, request, **kwargs)
            return form_field

        form_field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if form_field:
            form_field = self.assign_widget_to_form_field(form_field, db_field, request)
        return form_field


class SBAdminBaseFormInit(SBAdminFormFieldWidgetsMixin, FormFieldsetMixin):
    threadsafe_request = None
    view = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if not hasattr(self.fields[field].widget, "init_widget_dynamic"):
                continue
            self.fields[field].widget.init_widget_dynamic(
                self,
                self.fields[field],
                field,
                self.view,
                self.threadsafe_request,
            )
        for field in self.declared_fields:
            form_field = self.fields.get(field)
            if form_field:
                self.assign_widget_to_form_field(
                    form_field, request=self.threadsafe_request
                )


class SBAdminBaseForm(
    SBAdminBaseFormInit, forms.ModelForm, SBAdminFormFieldWidgetsMixin
):
    pass


if parler_enabled:

    class SBTranslatableModelFormMetaclass(ModelFormMetaclass):
        def parler_orig__new__(mcs, name, bases, attrs):
            # Before constructing class, fetch attributes from bases list.
            form_meta = _get_mro_attribute(bases, "_meta")
            form_base_fields = _get_mro_attribute(
                bases, "base_fields", {}
            )  # set by previous class level.

            if form_meta:
                # Not declaring the base class itself, this is a subclass.

                # Read the model from the 'Meta' attribute. This even works in the admin,
                # as `modelform_factory()` includes a 'Meta' attribute.
                # The other options can be read from the base classes.
                form_new_meta = attrs.get("Meta", form_meta)
                form_model = form_new_meta.model if form_new_meta else form_meta.model

                # Detect all placeholders at this class level.
                placeholder_fields = [
                    f_name
                    for f_name, attr_value in attrs.items()
                    if isinstance(attr_value, TranslatedField)
                ]

                # Include the translated fields as attributes, pretend that these exist on the form.
                # This also works when assigning `form = TranslatableModelForm` in the admin,
                # since the admin always uses modelform_factory() on the form class, and therefore triggering this metaclass.
                if form_model:
                    for translations_model in form_model._parler_meta.get_all_models():
                        fields = getattr(form_new_meta, "fields", form_meta.fields)
                        exclude = (
                            getattr(form_new_meta, "exclude", form_meta.exclude) or ()
                        )
                        widgets = (
                            getattr(form_new_meta, "widgets", form_meta.widgets) or ()
                        )
                        labels = (
                            getattr(form_new_meta, "labels", form_meta.labels) or ()
                        )
                        help_texts = (
                            getattr(form_new_meta, "help_texts", form_meta.help_texts)
                            or ()
                        )
                        error_messages = (
                            getattr(
                                form_new_meta,
                                "error_messages",
                                form_meta.error_messages,
                            )
                            or ()
                        )
                        formfield_callback = attrs.get("formfield_callback", None)

                        if fields == "__all__":
                            fields = None

                        for f_name in translations_model.get_translated_fields():
                            # Add translated field if not already added, and respect exclude options.
                            if f_name in placeholder_fields:
                                # The TranslatedField placeholder can be replaced directly with actual field, so do that.
                                attrs[f_name] = _get_model_form_field(
                                    translations_model,
                                    f_name,
                                    formfield_callback=formfield_callback,
                                    **attrs[f_name].kwargs,
                                )

                            # The next code holds the same logic as fields_for_model()
                            # The f.editable check happens in _get_model_form_field()
                            elif (
                                f_name not in form_base_fields
                                and (fields is None or f_name in fields)
                                and f_name not in exclude
                                and not f_name in attrs
                            ):
                                # Get declared widget kwargs
                                if f_name in widgets:
                                    # Not combined with declared fields (e.g. the TranslatedField placeholder)
                                    kwargs = {"widget": widgets[f_name]}
                                else:
                                    kwargs = {}

                                if f_name in help_texts:
                                    kwargs["help_text"] = help_texts[f_name]

                                if f_name in labels:
                                    kwargs["label"] = labels[f_name]

                                if f_name in error_messages:
                                    kwargs["error_messages"] = error_messages[f_name]

                                # See if this formfield was previously defined using a TranslatedField placeholder.
                                placeholder = _get_mro_attribute(bases, f_name)
                                if placeholder and isinstance(
                                    placeholder, TranslatedField
                                ):
                                    kwargs.update(placeholder.kwargs)

                                # Add the form field as attribute to the class.
                                formfield = _get_model_form_field(
                                    translations_model,
                                    f_name,
                                    formfield_callback=formfield_callback,
                                    **kwargs,
                                )
                                if formfield is not None:
                                    attrs[f_name] = formfield

        # patched due to Parler issue fetching formfield_callback from attributes istead of Meta object
        #
        # https://github.com/django-parler/django-parler/blob/v2.3/parler/forms.py#L276
        # parler/forms.py:276
        # formfield_callback = attrs.get("formfield_callback", None)
        def __new__(mcs, name, bases, attrs):
            form_base_fields = _get_mro_attribute(bases, "base_fields", {})
            meta = attrs.get("Meta", None)
            if meta:
                formfield_callback = (
                    getattr(meta, "formfield_callback", None) if meta else None
                )
                if formfield_callback:
                    attrs["formfield_callback"] = formfield_callback
                    # parler adds missing translated fields, but originally it adds it too soon, when formfield_callback
                    # is not yet defined (while only class is initializing not instance), resulting in skipping callback
                    mcs.parler_orig__new__(mcs, name, bases, attrs)
            return super().__new__(mcs, name, bases, attrs)

    class SBTranslatableModelForm(
        BaseTranslatableModelForm,
        SBAdminBaseForm,
        metaclass=SBTranslatableModelFormMetaclass,
    ):
        pass


class SBAdminInlineAndAdminCommon(SBAdminFormFieldWidgetsMixin):
    sbadmin_fake_inlines = None

    def init_view_static(self, configuration, model, admin_site):
        configuration.view_map[self.get_id()] = self
        inlines = getattr(self, "inlines") or []
        inlines = list(inlines)
        sbadmin_fake_inlines = getattr(self, "sbadmin_fake_inlines") or []
        inlines.extend(list(sbadmin_fake_inlines))
        for inline_view in inlines:
            if issubclass(inline_view, SBAdminInline):
                inline_view_instance = inline_view(model, admin_site)
                configuration.view_map[inline_view_instance.get_id()] = (
                    inline_view_instance
                )
                inline_view_instance.init_view_static(
                    configuration, inline_view_instance.model, admin_site
                )

    def get_sbadmin_fake_inlines(self, request, obj):
        return self.sbadmin_fake_inlines or []

    def get_inline_instances(self, request, obj=None):
        inline_classes = self.get_inlines(request, obj)
        inline_classes = [*inline_classes] or []
        inline_classes.extend(self.get_sbadmin_fake_inlines(request, obj))
        inlines = []
        for inline_class in inline_classes:
            inline = inline_class(self.model, self.admin_site)
            if request:
                if not inline.has_view_or_change_permission(request, obj):
                    continue
                if not inline.has_add_permission(request, obj):
                    inline.max_num = 0
            if hasattr(inline, "init_inline_dynamic"):
                inline.init_inline_dynamic(request, obj)
                inline.init_view_dynamic(request, request.request_data)
            inlines.append(inline)
        return inlines

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        if SBAdminTranslationsService.is_translated_model(self.model):
            has_default_form = (
                self.form == TranslatableModelForm or self.form == forms.ModelForm
            )
            if not self.form or has_default_form:
                self.form = SBTranslatableModelForm
            if self.form and not issubclass(self.form, SBTranslatableModelForm):
                raise ImproperlyConfigured(
                    f"Admin '{self}' form class '{self.form}' needs to extend SBTranslatableModelForm in case of translatable model."
                )
        super().init_view_dynamic(request, request_data, **kwargs)
        self.initialize_form_class(self.form)

    def initialize_form_class(self, form):
        if form:
            form.view = self

    def initialize_form_class_threadsafe(self, form, request):
        self.initialize_form_class(form)
        if form:
            form.threadsafe_request = request


class SBAdminThirdParty(SBAdminInlineAndAdminCommon, SBAdminBaseView):
    def get_menu_view_url(self, request):
        return reverse(f"sb_admin:{self.get_id()}_changelist")

    def get_id(self):
        return self.get_model_path()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        return super().changelist_view(request, extra_context)

    def get_action_url(self, action, modifier="template"):
        return reverse(
            f"sb_admin:{self.get_id()}_action",
            kwargs={"action": action, "modifier": modifier},
        )


class SBAdminTranslationStatusMixin:
    def sbadmin_translation_status_row_context(
        self,
        language,
        languages_count,
        main_language_code,
        current_lang_code,
        translations_edit_url,
    ):
        language_code = language[0]
        language_title = language[1]
        this_lang_count = languages_count.get(language_code, 0)
        main_language_count = languages_count.get(main_language_code, 0)
        status_icon = "Attention"
        status_icon_color = "text-warning"
        edit_icon = "Write"
        edit_icon_color = (
            "text-dark hover:text-dark-900 transition-colors cursor-pointer"
        )
        text_color = "text-dark-900"
        if this_lang_count == main_language_count:
            status_icon = "Check"
            status_icon_color = "text-success"
        if language_code == current_lang_code:
            language_title = f"<strong>{language_title} ({_('active')})</strong>"
            edit_icon_color = "invisible"
        if this_lang_count == 0:
            status_icon_color = "invisible"
            text_color = ""
            edit_icon = "Add-one"
        return {
            "text_color": text_color,
            "language_title": language_title,
            "status_icon_color": status_icon_color,
            "status_icon": status_icon,
            "edit_icon": edit_icon,
            "edit_icon_color": edit_icon_color,
            "lang": language,
            "flag_url": f"sb_admin/images/flags/{language_code}.png",
            "translations_edit_url": translations_edit_url,
            "TRANSLATIONS_SELECTED_LANGUAGES": TRANSLATIONS_SELECTED_LANGUAGES,
        }

    @classmethod
    def get_empty_state(cls):
        return mark_safe("<div class='is-empty'></div>")

    @admin.display(description="")
    def sbadmin_translation_status(self, obj):
        if not SBAdminTranslationsService.is_i18n_enabled():
            return self.get_empty_state()

        translations_view_id = SBAdminTranslationsService.get_translation_view_id(
            self.model
        )
        translations_edit_url = (
            SBAdminTranslationsService.get_model_translation_detail_url(
                translations_view_id, obj.id
            )
        )
        result = f"<a href='{translations_edit_url}' class='btn btn-small absolute top-24 right-24'>{_('Edit')}</a>"
        languages = SBAdminTranslationsService.get_all_languages()
        translations = (
            SBAdminTranslationsService.annotate_queryset_with_translations_count(
                self.model.objects.filter(id=obj.id),
                self.model,
                [lang[0] for lang in languages],
            )
            .values()
            .first()
        )
        translation_counts = {}
        for key, value in translations.items():
            if key.endswith("_count"):
                for lang in languages:
                    if key.endswith(f"{lang[0]}_count"):
                        translation_counts[lang[0]] = value
        main_lang_code = SBAdminTranslationsService.get_main_lang_code()
        for index, lang in enumerate(languages):
            result += render_to_string(
                "sb_admin/actions/partials/translations_status_row.html",
                context=self.sbadmin_translation_status_row_context(
                    lang,
                    translation_counts,
                    main_lang_code,
                    main_lang_code,
                    translations_edit_url,
                ),
            )
        return mark_safe(result)


class SBAdmin(
    SBAdminInlineAndAdminCommon,
    SBAdminBaseQuerysetMixin,
    SBAdminBaseListView,
    SBAdminTranslationStatusMixin,
    NestedModelAdmin,
):
    change_list_template = "sb_admin/actions/list.html"
    change_form_template = "sb_admin/actions/change_form.html"
    delete_confirmation_template = "sb_admin/actions/delete_confirmation.html"
    delete_selected_confirmation_template = (
        "sb_admin/actions/delete_selected_confirmation.html"
    )
    object_history_template = "sb_admin/actions/object_history.html"

    sbadmin_fieldsets = None
    sbadmin_previous_next_buttons_enabled = False
    sbadmin_tabs = None
    request_data = None
    menu_label = None

    def get_sbadmin_list_filter(self, request):
        return self.sbadmin_list_filter or self.get_list_filter(request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        self.initialize_form_class_threadsafe(form, request)
        return form

    def get_id(self):
        return self.get_model_path()

    def get_sbadmin_fieldsets(self, request, object_id=None):
        fieldsets = self.sbadmin_fieldsets or self.fieldsets
        if fieldsets:
            return fieldsets
        raise ImproperlyConfigured(
            f"{self} is missing definition of fieldsets or sbadmin_fieldsets."
        )

    def register_autocomplete_views(self, request):
        self.get_form(request)()

    def get_fieldsets(self, request, obj):
        fieldsets = []
        object_id = obj.id if obj else None
        for fieldset in self.get_sbadmin_fieldsets(request, object_id):
            fieldset_dict = {"fields": fieldset[1].get("fields")}
            classes = fieldset[1].get("classes")
            description = fieldset[1].get("description")
            if classes:
                fieldset_dict["classes"] = classes
            if description:
                fieldset_dict["description"] = description
            fieldset_django = (fieldset[0], fieldset_dict)
            fieldsets.append(fieldset_django)
        return fieldsets

    def get_fieldsets_context(self, request, object_id):
        fielsets_context = {}
        for fieldset in self.get_sbadmin_fieldsets(request, object_id):
            actions = fieldset[1].get("actions", [])
            for index, action in enumerate(actions):
                if isinstance(action, SBAdminCustomAction):
                    continue
                try:
                    actions[index] = getattr(self, action)()
                except AttributeError:
                    pass
            fielsets_context[fieldset[0]] = fieldset[1]
        return {"fieldsets_context": fielsets_context}

    def get_sbadmin_tabs(self, request, object_id):
        return self.sbadmin_tabs

    def get_tabs_context(self, request, object_id):
        return {"tabs_context": self.get_sbadmin_tabs(request, object_id)}

    def get_context_data(self, request):
        return {
            "base_change_list_template": self.change_list_template,
        }

    def get_menu_view_url(self, request):
        all_config = self.get_all_config(request)
        url_suffix = ""
        if all_config and all_config.get("all_params_changed", False):
            url_params_dict = all_config.get("url_params")
            if url_params_dict:
                url_suffix = f"?{SBAdminViewService.build_list_url(self.get_id(), url_params_dict)}"

        return f'{reverse(f"sb_admin:{self.get_id()}_changelist")}{url_suffix}'

    def get_menu_label(self):
        return self.menu_label or self.model._meta.verbose_name_plural

    def get_action_url(self, action, modifier="template"):
        if not hasattr(self, action):
            raise ImproperlyConfigured(f"Action {action} does not exist on {self}")
        return reverse(
            f"sb_admin:{self.get_id()}_action",
            kwargs={
                "action": action,
                "modifier": (
                    urllib.parse.quote(str(modifier), safe="") if modifier else None
                ),
            },
        )

    def get_detail_url(self, object_id=None):
        return reverse(
            f"sb_admin:{self.get_id()}_change",
            kwargs={"object_id": object_id or OBJECT_ID_PLACEHOLDER},
        )

    def get_new_url(self):
        return reverse(f"sb_admin:{self.get_id()}_add")

    def get_previous_next_context(self, request, object_id):
        if not self.sbadmin_previous_next_buttons_enabled or not object_id:
            return {}
        changelist_filters = request.GET.get("_changelist_filters", "")
        try:
            all_params = json.loads(
                urllib.parse.parse_qs(urllib.parse.unquote(changelist_filters))[
                    "params"
                ][0]
            )
        except:
            all_params = {}
        list_action = SBAdminListAction(self, request, all_params=all_params)
        all_ids = list(
            list_action.build_final_data_count_queryset()
            .order_by(*list_action.get_order_by_from_request())
            .values_list("id", flat=True)
        )
        index = all_ids.index(int(object_id))
        previous_id = None if index == 0 else all_ids[index - 1]
        next_id = None if index == len(all_ids) - 1 else all_ids[index + 1]
        return {
            "previous_url": (
                f"{self.get_detail_url(previous_id)}?_changelist_filters={changelist_filters}"
                if previous_id
                else None
            ),
            "current_index": index + 1,
            "all_objects_count": len(all_ids),
            "next_url": (
                f"{self.get_detail_url(next_id)}?_changelist_filters={changelist_filters}"
                if next_id
                else None
            ),
        }

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request, object_id))
        extra_context.update(self.get_fieldsets_context(request, object_id))
        extra_context.update(self.get_tabs_context(request, object_id))
        extra_context.update(self.get_previous_next_context(request, object_id))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.action_list(request, extra_context=extra_context)


class SBAdminInline(
    SBAdminInlineAndAdminCommon, SBAdminBaseQuerysetMixin, SBAdminBaseView
):
    sortable_field_name = None
    parent_instance = None
    sbadmin_sortable_field_options = ["order_by"]
    sbadmin_inline_list_actions = None
    extra = 0

    def get_sbadmin_inline_list_actions(self):
        return [*(self.sbadmin_inline_list_actions or [])]

    def get_action_url(self, action, modifier="template"):
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": action,
                "modifier": modifier,
            },
        )

    def register_autocomplete_views(self, request):
        super().register_autocomplete_views(request)
        form_class = self.get_formset(request, self.model()).form
        self.initialize_form_class_threadsafe(form_class, request)
        form_class()

    @property
    def get_context_data(self):
        return {"inline_list_actions": self.get_sbadmin_inline_list_actions()}

    def init_sortable_field(self):
        if not self.sortable_field_name:
            for field_name in self.sbadmin_sortable_field_options:
                is_sortable_field_present = False
                try:
                    is_sortable_field_present = self.model._meta.get_field(field_name)
                except FieldDoesNotExist:
                    pass
                if is_sortable_field_present:
                    self.sortable_field_name = field_name
                    break

    def __init__(self, parent_model, admin_site) -> None:
        self.init_sortable_field()
        super().__init__(parent_model, admin_site)

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        return super().init_view_dynamic(request, request_data, **kwargs)

    def get_id(self):
        return (
            f"{self.__class__.__name__}_{SBAdminViewService.get_model_path(self.model)}"
        )

    def init_inline_dynamic(self, request, obj=None):
        self.threadsafe_request = request
        self.parent_instance = obj

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == self.sortable_field_name:
            formfield.widget = HiddenInput()
        return formfield

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        form_class = formset.form
        self.initialize_form_class_threadsafe(form_class, request)
        return formset


class SBAdminTableInline(SBAdminInline, NestedTabularInline):
    template = "sb_admin/inlines/table_inline.html"


class SBAdminGenericTableInline(SBAdminInline, NestedGenericTabularInline):
    template = "sb_admin/inlines/table_inline.html"


class SBAdminTableInlinePaginated(SBAdminTableInline, TabularInlinePaginated):
    template = "sb_admin/inlines/table_inline_paginated.html"
    per_page = 50


class SBAdminGenericTableInlinePaginated(SBAdminGenericTableInline):
    template = "sb_admin/inlines/table_inline_paginated.html"
    per_page = 50


class SBAdminStackedInline(SBAdminInline, NestedStackedInline):
    template = "sb_admin/inlines/stacked_inline.html"
    fieldset_template = "sb_admin/includes/inline_fieldset.html"


class SBAdminGenericStackedInline(SBAdminInline, NestedGenericStackedInline):
    template = "sb_admin/inlines/stacked_inline.html"
    fieldset_template = "sb_admin/includes/inline_fieldset.html"
