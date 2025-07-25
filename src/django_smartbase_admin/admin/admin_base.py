import json
import logging
import urllib.parse
from collections.abc import Iterable
from functools import partial
from typing import Any

from ckeditor.fields import RichTextFormField
from ckeditor_uploader.fields import RichTextUploadingFormField
from django import forms
from django.contrib import admin
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.admin.utils import unquote
from django.contrib.admin.widgets import AdminTextareaWidget
from django.contrib.auth.forms import UsernameField, ReadOnlyPasswordHashWidget
from django.contrib.contenttypes.forms import BaseGenericInlineFormSet
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    PermissionDenied,
)
from django.db import models
from django.db.models import QuerySet, Q
from django.forms import HiddenInput
from django.forms.models import (
    ModelFormMetaclass,
    modelform_factory,
)
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import reverse, NoReverseMatch
from django.utils.safestring import mark_safe, SafeString
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from django_admin_inline_paginator.admin import TabularInlinePaginated
from django_htmx.http import trigger_client_event
from parler.admin import TranslatableAdmin

from django_smartbase_admin.engine.field import SBAdminField
from filer.fields.file import FilerFileField
from filer.fields.image import AdminImageFormField, FilerImageField
from nested_admin.formsets import NestedInlineFormSet
from nested_admin.nested import (
    NestedModelAdmin,
    NestedTabularInline,
    NestedGenericTabularInline,
    NestedStackedInline,
    NestedGenericStackedInline,
)

from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.utils import FormFieldsetMixin, is_modal

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

postrgres_enabled = None
try:
    from django.contrib.postgres.forms import SimpleArrayField

    postrgres_enabled = True
except ImportError:
    pass

django_cms_attributes = None
try:
    from djangocms_attributes_field.fields import AttributesFormField

    django_cms_attributes = True
except ImportError:
    pass

color_field_enabled = None
try:
    from colorfield.fields import ColorField

    color_field_enabled = True
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
    SBAdminFileWidget,
    SBAdminToggleWidget,
    SBAdminNullBooleanSelectWidget,
    SBAdminArrayWidget,
    SBAdminImageWidget,
    SBAdminPasswordInputWidget,
    SBAdminReadOnlyPasswordHashWidget,
    SBAdminHiddenWidget,
    SBAdminCKEditorUploadingWidget,
    SBAdminAttributesWidget,
    SBAdminMultipleChoiceInlineWidget,
    SBAdminColorWidget,
    SBAdminFilerFileWidget,
)
from django_smartbase_admin.engine.admin_base_view import (
    SBAdminBaseListView,
    SBAdminBaseView,
    SBAdminBaseQuerysetMixin,
    SBADMIN_IS_MODAL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
)
from django_smartbase_admin.engine.const import (
    OBJECT_ID_PLACEHOLDER,
    TRANSLATIONS_SELECTED_LANGUAGES,
    ROW_CLASS_FIELD,
    Action,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.views import SBAdminViewService

logger = logging.getLogger(__name__)


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
        RichTextUploadingFormField: SBAdminCKEditorUploadingWidget,
        forms.ChoiceField: SBAdminSelectWidget,
        forms.TypedChoiceField: SBAdminSelectWidget,
        forms.MultipleChoiceField: SBAdminMultipleChoiceInlineWidget,
        forms.TypedMultipleChoiceField: SBAdminMultipleChoiceInlineWidget,
        forms.NullBooleanField: SBAdminNullBooleanSelectWidget,
        AdminImageFormField: SBAdminImageWidget,
        ReadOnlyPasswordHashWidget: SBAdminReadOnlyPasswordHashWidget,
        forms.HiddenInput: SBAdminHiddenWidget,
    }
    db_field_widgets = {
        FilerImageField: SBAdminFilerFileWidget,
        FilerFileField: SBAdminFilerFileWidget,
    }
    if postrgres_enabled:
        formfield_widgets[SimpleArrayField] = SBAdminArrayWidget
    if django_cms_attributes:
        formfield_widgets[AttributesFormField] = SBAdminAttributesWidget
    if color_field_enabled:
        db_field_widgets[ColorField] = SBAdminColorWidget

    django_widget_to_widget = {
        forms.PasswordInput: SBAdminPasswordInputWidget,
        AdminTextareaWidget: SBAdminTextareaWidget,
    }

    def get_form_field_widget_class(self, form_field, db_field, request):
        default_widget_class = self.db_field_widgets.get(
            db_field.__class__, self.formfield_widgets.get(form_field.__class__)
        )
        if not hasattr(request, "request_data"):
            # in case of login the view is not wrapped and we have no request_data present
            return default_widget_class
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
        kwargs = {}
        if isinstance(form_field, RichTextFormField):
            kwargs["config_name"] = getattr(
                form_field.widget, "config_name", None
            ) or getattr(db_field, "config_name", "default")

            kwargs["external_plugin_resources"] = getattr(
                form_field.widget, "external_plugin_resources", None
            ) or getattr(db_field, "external_plugin_resources", [])
            kwargs["extra_plugins"] = getattr(
                form_field.widget, "extra_plugins", None
            ) or getattr(db_field, "extra_plugins", [])
        form_field.widget = widget(form_field=form_field, attrs=widget_attrs, **kwargs)
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
                    db_field,
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
    view = None

    def __init__(self, *args, **kwargs):
        self.view = kwargs.pop("view", self.view)
        threadsafe_request = kwargs.pop(
            "request", SBAdminThreadLocalService.get_request()
        )
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if not hasattr(self.fields[field].widget, "init_widget_dynamic"):
                continue
            self.fields[field].widget.init_widget_dynamic(
                self,
                self.fields[field],
                field,
                self.view,
                threadsafe_request,
            )
        for field in self.declared_fields:
            form_field = self.fields.get(field)
            if form_field:
                self.assign_widget_to_form_field(form_field, request=threadsafe_request)


class SBAdminBaseForm(SBAdminBaseFormInit, forms.ModelForm):
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
    all_base_fields_form = None

    def init_view_static(self, configuration, model, admin_site):
        configuration.view_map[self.get_id()] = self
        inlines = getattr(self, "inlines") or []
        inlines = list(inlines)
        sbadmin_fake_inlines = getattr(self, "sbadmin_fake_inlines") or []
        inlines.extend(list(sbadmin_fake_inlines))
        for inline_view in inlines:
            if issubclass(inline_view, SBAdminInline):
                inline_view_instance = inline_view(model, admin_site)
                inline_view_instance.init_view_static(
                    configuration, inline_view_instance.model, admin_site
                )

    def get_sbadmin_fake_inlines(self, request, obj) -> Iterable:
        return self.sbadmin_fake_inlines or []

    def get_inline_instances(self, request, obj=None) -> list:
        inline_classes = self.get_inlines(request, obj)
        inline_classes = [*inline_classes] or []
        inline_classes.extend(self.get_sbadmin_fake_inlines(request, obj))
        inlines = []
        for inline_class in inline_classes:
            inline = inline_class(self.model, self.admin_site)
            if hasattr(inline, "init_inline_dynamic"):
                inline.init_inline_dynamic(request, obj)
            if request:
                if not inline.has_view_or_change_permission(request, obj):
                    continue
                if not inline.has_add_permission(request, obj):
                    inline.max_num = 0
            if hasattr(inline, "init_view_dynamic"):
                inline.init_view_dynamic(request, request.request_data)
            inlines.append(inline)
        return inlines

    def init_view_dynamic(self, request, request_data=None, **kwargs) -> None:
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
        self.initialize_form_class(self.form, request)

    def initialize_form_class(self, form, request) -> None:
        if form:
            form.view = self

    def initialize_all_base_fields_form(self, request) -> None:
        params = {
            "form": self.form,
            "fields": "__all__",
            "formfield_callback": partial(self.formfield_for_dbfield, request=request),
        }
        self.all_base_fields_form = modelform_factory(self.model, **params)


class SBAdminThirdParty(SBAdminInlineAndAdminCommon, SBAdminBaseView):
    def get_menu_view_url(self, request) -> str:
        return reverse(f"sb_admin:{self.get_id()}_changelist")

    def get_id(self) -> str:
        return self.get_model_path()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        return super().changelist_view(request, extra_context)

    def get_action_url(self, action, modifier="template") -> str:
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": action,
                "modifier": modifier,
            },
        )


class SBAdminTranslationStatusMixin:
    def sbadmin_translation_status_row_context(
        self,
        language,
        languages_count,
        main_language_code,
        current_lang_code,
        translations_edit_url,
    ) -> dict[str, Any]:
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
    def get_empty_state(cls) -> SafeString:
        return mark_safe("<div class='is-empty'></div>")

    @admin.display(description="")
    def sbadmin_translation_status(self, obj) -> SafeString:
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


class SBAdminInlineFormSetMixin:
    @classmethod
    def get_default_prefix(cls):
        view = getattr(cls.form, "view", None)
        if view and view.parent_model and view.opts:
            parent_opts = view.parent_model._meta
            opts = view.opts
            modal_prefix = (
                "modal_" if is_modal(SBAdminThreadLocalService.get_request()) else ""
            )
            return f"{modal_prefix}{parent_opts.app_label}_{parent_opts.model_name}_{opts.app_label}-{opts.model_name}"

        return super().get_default_prefix()


class SBAdminGenericInlineFormSet(SBAdminInlineFormSetMixin, BaseGenericInlineFormSet):
    pass


class SBAdminNestedInlineFormSet(SBAdminInlineFormSetMixin, NestedInlineFormSet):
    pass


class SBAdmin(
    SBAdminInlineAndAdminCommon,
    SBAdminBaseQuerysetMixin,
    SBAdminBaseListView,
    SBAdminTranslationStatusMixin,
    NestedModelAdmin,
):
    change_list_template = "sb_admin/actions/list.html"
    reorder_list_template = "sb_admin/actions/list.html"
    change_form_template = "sb_admin/actions/change_form.html"
    delete_selected_confirmation_template = (
        "sb_admin/actions/delete_selected_confirmation.html"
    )
    object_history_template = "sb_admin/actions/object_history.html"

    sbadmin_fieldsets = None
    sbadmin_previous_next_buttons_enabled = False
    sbadmin_tabs = None
    request_data = None
    menu_label = None
    sbadmin_is_generic_model = False

    def save_formset(self, request, form, formset, change):
        if not change and hasattr(formset, "inline_instance"):
            # update inline_instance parent_instance on formset when creating new object
            formset.inline_instance.parent_instance = form.instance
        super().save_formset(request, form, formset, change)

    def get_sbadmin_list_filter(self, request) -> Iterable:
        return self.sbadmin_list_filter or self.get_list_filter(request)

    def get_form(self, request, obj=None, **kwargs):
        self.initialize_all_base_fields_form(request)
        form = super().get_form(request, obj, **kwargs)
        self.initialize_form_class(form, request)
        return form

    def get_id(self) -> str:
        return self.get_model_path()

    def get_sbadmin_fieldsets(
        self, request, object_id=None
    ) -> Iterable[tuple[str | None, dict[str, Any]]]:
        fieldsets = self.sbadmin_fieldsets or self.fieldsets
        if fieldsets:
            return fieldsets
        raise ImproperlyConfigured(
            f"{self} is missing definition of fieldsets or sbadmin_fieldsets."
        )

    def register_autocomplete_views(self, request):
        super().register_autocomplete_views(request)
        self.get_form(request)()

    def get_fieldsets(
        self, request, obj=None
    ) -> list[tuple[str | None, dict[str, Any]]]:
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

    def get_fieldsets_context(
        self, request, object_id
    ) -> dict[str, dict[str | None, dict[str, Any]]]:
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

    def get_sbadmin_tabs(self, request, object_id) -> Iterable:
        return self.sbadmin_tabs

    def get_tabs_context(self, request, object_id) -> dict[str, Iterable]:
        return {"tabs_context": self.get_sbadmin_tabs(request, object_id)}

    def get_context_data(self, request) -> dict[str, Any]:
        return {
            "base_change_list_template": self.change_list_template,
        }

    def get_menu_view_url(self, request) -> str:
        all_config = self.get_all_config(request)
        url_suffix = ""
        if all_config and all_config.get("all_params_changed", False):
            url_params_dict = SBAdminViewService.process_url_params(
                view_id=self.get_id(),
                url_params=all_config.get("url_params"),
                filter_version=self.get_filters_version(request),
            )
            if url_params_dict:
                url_suffix = f"?{SBAdminViewService.build_list_url(self.get_id(), url_params_dict)}"

        return f'{reverse(f"sb_admin:{self.get_id()}_changelist")}{url_suffix}'

    def get_menu_label(self) -> str:
        return self.menu_label or self.model._meta.verbose_name_plural

    def get_action_url(self, action, modifier="template") -> str:
        if not hasattr(self, action):
            raise ImproperlyConfigured(f"Action {action} does not exist on {self}")
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": action,
                "modifier": modifier,
            },
        )

    def get_detail_url(self, object_id=None) -> str:
        return reverse(
            f"sb_admin:{self.get_id()}_change",
            kwargs={"object_id": object_id or OBJECT_ID_PLACEHOLDER},
        )

    def get_new_url(self, request) -> str:
        return reverse(f"sb_admin:{self.get_id()}_add")

    def get_additional_filter_for_previous_next_context(self, request, object_id) -> Q:
        return Q()

    def get_change_view_context(self, request, object_id) -> dict | dict[str, Any]:
        return {"show_back_button": True}

    def get_previous_next_context(self, request, object_id) -> dict | dict[str, Any]:
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
        list_action = self.sbadmin_list_action_class(
            self, request, all_params=all_params
        )
        additional_filter = self.get_additional_filter_for_previous_next_context(
            request, object_id
        )
        all_ids = list(
            list_action.build_final_data_count_queryset(additional_filter)
            .order_by(*list_action.get_order_by_from_request())
            .values_list("id", flat=True)
        )
        index = all_ids.index(int(object_id))
        previous_id = all_ids[-1] if index == 0 else all_ids[index - 1]
        next_id = all_ids[0] if index == len(all_ids) - 1 else all_ids[index + 1]
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

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request, None))
        extra_context.update(self.get_fieldsets_context(request, None))
        extra_context.update(self.get_tabs_context(request, None))
        return self.changeform_view(request, None, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_change_view_context(request, object_id))
        extra_context.update(self.get_global_context(request, object_id))
        extra_context.update(self.get_fieldsets_context(request, object_id))
        extra_context.update(self.get_tabs_context(request, object_id))
        extra_context.update(self.get_previous_next_context(request, object_id))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.action_list(request, extra_context=extra_context)

    def history_view(self, request, object_id, extra_context=None):
        try:
            "The 'history' admin view for this model."
            from django.contrib.admin.models import LogEntry
            from django.contrib.admin.views.main import PAGE_VAR

            # First check if the user can see this history.
            model = self.model
            obj = self.get_object(request, unquote(object_id))
            if obj is None:
                return self._get_obj_does_not_exist_redirect(
                    request, model._meta, object_id
                )

            if not self.has_view_or_change_permission(request, obj):
                raise PermissionDenied

            # Then get the history for this object.
            app_label = self.opts.app_label
            action_list = (
                LogEntry.objects.filter(
                    object_id=unquote(object_id),
                    content_type=get_content_type_for_model(model),
                )
                .select_related()
                .order_by("-action_time")
            )

            paginator = self.get_paginator(request, action_list, 100)
            page_number = request.GET.get(PAGE_VAR, 1)
            page_obj = paginator.get_page(page_number)
            page_range = paginator.get_elided_page_range(page_obj.number)

            context = {
                **self.admin_site.each_context(request),
                "title": _("Change history: %s") % obj,
                "subtitle": None,
                "action_list": page_obj,
                "page_range": page_range,
                "page_var": PAGE_VAR,
                "pagination_required": paginator.count > 100,
                "module_name": str(capfirst(self.opts.verbose_name_plural)),
                "object": obj,
                "opts": self.opts,
                "preserved_filters": self.get_preserved_filters(request),
                **(extra_context or {}),
            }

            request.current_app = self.admin_site.name

            return TemplateResponse(
                request,
                self.object_history_template
                or [
                    "admin/%s/%s/object_history.html"
                    % (app_label, self.opts.model_name),
                    "admin/%s/object_history.html" % app_label,
                    "admin/object_history.html",
                ],
                context,
            )
        except Exception as e:
            return super().history_view(request, object_id, extra_context)

    @classmethod
    def get_modal_save_response(cls, request, obj):
        response = HttpResponse()
        trigger_client_event(
            response,
            "sbadmin:modal-change-form-response",
            {
                "field": request.POST.get("sb_admin_source_field"),
                "id": obj.pk,
                "label": str(obj),
                "reload": request.POST.get("sbadmin_reload_on_save") == "1",
            },
        )
        trigger_client_event(response, "hideModal", {"elt": "sb-admin-modal"})
        return response

    def response_add(self, request, obj, post_url_continue=None):
        if is_modal(request):
            return self.get_modal_save_response(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if is_modal(request):
            return self.get_modal_save_response(request, obj)
        return super().response_change(request, obj)

    @classmethod
    def set_generic_relation_from_parent(cls, request, obj):
        parent_model_path = request.POST.get(SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR)
        parent_pk = request.POST.get(SBADMIN_PARENT_INSTANCE_PK_VAR)

        if parent_model_path and parent_pk:
            prefix, app_label, model_name, field, parent_model = (
                parent_model_path.split("_", 5)
            )
            content_type = ContentType.objects.get(
                app_label=app_label, model=parent_model
            )
            obj.content_type = content_type
            obj.object_id = int(parent_pk)

    def save_model(self, request, obj, form, change):
        if self.sbadmin_is_generic_model and SBADMIN_IS_MODAL_VAR in request.POST:
            self.set_generic_relation_from_parent(request, obj)
        super().save_model(request, obj, form, change)


class SBAdminInline(
    SBAdminInlineAndAdminCommon, SBAdminBaseQuerysetMixin, SBAdminBaseView
):
    sortable_field_name = None
    parent_instance = None
    sbadmin_sortable_field_options = ["order_by"]
    sbadmin_inline_list_actions = None
    extra = 0
    ordering = None
    all_base_fields_form = None
    sb_admin_add_modal = False

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        if ROW_CLASS_FIELD not in readonly_fields:
            readonly_fields += (ROW_CLASS_FIELD,)
        return readonly_fields

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if ROW_CLASS_FIELD not in fields:
            fields += (ROW_CLASS_FIELD,)
        return fields

    def get_sbadmin_row_class(self, obj):
        return ""

    def get_ordering(self, request) -> tuple[str]:
        """
        Hook for specifying field ordering.
        """
        return self.ordering or ("-id",)

    def get_queryset(self, request=None) -> QuerySet:
        qs = super().get_queryset(request)
        return qs.order_by(*self.get_ordering(request))

    def get_sbadmin_inline_list_actions(self, request) -> list:
        return [*(self.sbadmin_inline_list_actions or [])]

    def get_action_url(self, action, modifier="template") -> str:
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": action,
                "modifier": modifier,
            },
        )

    def register_autocomplete_views(self, request) -> None:
        super().register_autocomplete_views(request)
        form_class = self.get_formset(request, self.model()).form
        self.initialize_form_class(form_class, request)
        form_class()

    def get_context_data(self, request) -> dict[str, Any]:
        is_sortable_active: bool = self.sortable_field_name and (
            self.has_add_permission(request) or self.has_change_permission(request)
        )
        add_url = None
        try:
            if self.sb_admin_add_modal and self.has_add_permission(request):
                add_url = reverse(
                    "sb_admin:{}_{}_add".format(
                        self.opts.app_label, self.opts.model_name
                    )
                )
        except NoReverseMatch:
            logger.warning(
                "To use Add in modal, You have to specify SBAdmin view for %s model",
                self.opts.model_name,
            )
        context_data = {
            "inline_list_actions": self.get_sbadmin_inline_list_actions(request),
            "is_sortable_active": is_sortable_active,
            "add_url": add_url,
        }
        if self.parent_instance:
            context_data["parent_data"] = {
                SBADMIN_PARENT_INSTANCE_PK_VAR: self.parent_instance.pk,
                SBADMIN_PARENT_INSTANCE_LABEL_VAR: str(self.parent_instance),
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: "{}_{}_id_{}".format(
                    self.model._meta.app_label,
                    self.model._meta.model_name,
                    self.parent_model._meta.model_name,
                ),
            }
        return context_data

    def init_sortable_field(self) -> None:
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

    def init_view_dynamic(self, request, request_data=None, **kwargs) -> None:
        return super().init_view_dynamic(request, request_data, **kwargs)

    def get_id(self) -> str:
        return (
            f"{self.__class__.__name__}_{SBAdminViewService.get_model_path(self.model)}"
        )

    def init_inline_dynamic(self, request, obj=None) -> None:
        self.threadsafe_request = request
        self.parent_instance = obj

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == self.sortable_field_name:
            formfield.widget = HiddenInput()
        return formfield

    def get_formset(self, request, obj=None, **kwargs):
        self.initialize_all_base_fields_form(request)
        formset = super().get_formset(request, obj, **kwargs)
        form_class = formset.form
        self.initialize_form_class(form_class, request)
        return formset


class SBAdminTableInline(SBAdminInline, NestedTabularInline):
    template = "sb_admin/inlines/table_inline.html"
    formset = SBAdminNestedInlineFormSet


class SBAdminGenericTableInline(SBAdminInline, NestedGenericTabularInline):
    template = "sb_admin/inlines/table_inline.html"
    formset = SBAdminGenericInlineFormSet


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


class SBTranslatableAdmin(SBAdmin, TranslatableAdmin):
    def get_readonly_fields(self, request, obj=...):
        readonly_fields = super().get_readonly_fields(request, obj)
        if "sbadmin_translation_status" not in readonly_fields:
            readonly_fields += ("sbadmin_translation_status",)
        return readonly_fields

    def get_fieldsets(self, request, obj=...):
        fieldsets = super().get_fieldsets(request, obj)
        fieldsets.append(SBAdminTranslationsService.get_translation_fieldset())
        return fieldsets
