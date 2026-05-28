import json
import logging
import urllib.parse
from collections.abc import Iterable
from copy import copy
from functools import partial
from typing import Any
from urllib.parse import urlparse

from ckeditor.fields import RichTextFormField
from ckeditor_uploader.fields import RichTextUploadingFormField
from django import forms
from django.conf import settings
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
    ValidationError,
)
from django.db import models
from django.db.models import QuerySet, Q, Model
from django.forms import HiddenInput
from django.forms.models import (
    ModelFormMetaclass,
    modelform_factory,
)
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import reverse, NoReverseMatch, resolve
from django.utils.safestring import mark_safe, SafeString
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from django_admin_inline_paginator.admin import TabularInlinePaginated
from django_htmx.http import trigger_client_event
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

from django_smartbase_admin.audit.views import (
    redirect_to_audit_history,
)
from django_smartbase_admin.engine.actions import SBAdminCustomAction, sbadmin_action
from django_smartbase_admin.engine.fake_inline import SBAdminFakeInlineMixin
from django_smartbase_admin.engine.dynamic_forms import (
    SBADMIN_DYNAMIC_REGION_ADD_MODIFIER,
    SBADMIN_DYNAMIC_REGION_PREFIX_PARAM,
    SBADMIN_DYNAMIC_REGION_PARAM,
    SBAdminDynamicFormMixin,
    dynamic_region_initial_from_data,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.utils import (
    FormFieldsetMixin,
    is_modal,
    render_notifications,
)

parler_enabled = None
try:
    from parler.admin import TranslatableAdmin

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
    from django.contrib.postgres.forms import SimpleArrayField, DateTimeRangeField

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

cms_enabled = None
try:
    from cms.forms.fields import PageSelectFormField

    cms_enabled = True
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
    SBAdminDateTimeRangeWidget,
)
from django_smartbase_admin.engine.admin_base_view import (
    SBAdminBaseListView,
    SBAdminBaseView,
    SBAdminBaseQuerysetMixin,
    SBADMIN_IS_MODAL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
    SBADMIN_RELOAD_ON_SAVE_VAR,
)
from django_smartbase_admin.engine.const import (
    OBJECT_ID_PLACEHOLDER,
    TRANSLATIONS_SELECTED_LANGUAGES,
    ROW_CLASS_FIELD,
    TABLE_RELOAD_DATA_EVENT_NAME,
    TABLE_PARAMS_NAME,
    TABLE_PARAMS_PAGE_NAME,
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
        formfield_widgets[DateTimeRangeField] = SBAdminDateTimeRangeWidget
    if django_cms_attributes:
        formfield_widgets[AttributesFormField] = SBAdminAttributesWidget
    if color_field_enabled:
        db_field_widgets[ColorField] = SBAdminColorWidget
    if cms_enabled:
        from django_smartbase_admin.admin.widgets import SBAdminPageSelectWidget

        formfield_widgets[PageSelectFormField] = SBAdminPageSelectWidget

    django_widget_to_widget = {
        forms.HiddenInput: SBAdminHiddenWidget,
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
        widget_attrs = form_field.widget.attrs
        widget_attrs.pop(
            "class", None
        )  # remove origin classes to prevent override our custom widget class
        kwargs = {}
        if choices:
            kwargs["choices"] = choices
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
    sbadmin_action_id = None

    def __init__(self, *args, **kwargs):
        self.view = kwargs.pop("view", self.view)
        self.sbadmin_action_id = kwargs.pop("sbadmin_action_id", self.sbadmin_action_id)
        threadsafe_request = kwargs.pop(
            "request", SBAdminThreadLocalService.get_request()
        )
        self.request = threadsafe_request
        super().__init__(*args, **kwargs)
        self.init_widgets_dynamic(threadsafe_request)
        model = getattr(getattr(self, "_meta", None), "model", None)
        for field_name, form_field in self.fields.items():
            db_field = None
            if model is not None:
                try:
                    db_field = model._meta.get_field(field_name)
                except FieldDoesNotExist:
                    db_field = None
            self.assign_widget_to_form_field(
                form_field,
                db_field=db_field,
                request=threadsafe_request,
            )

    def init_widgets_dynamic(self, request):
        for field in self.fields:
            if not hasattr(self.fields[field].widget, "init_widget_dynamic"):
                continue
            self.fields[field].widget.init_widget_dynamic(
                self,
                self.fields[field],
                field,
                self.view,
                request,
            )


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
    sbadmin_fieldsets = None
    sbadmin_fake_inlines = None
    all_base_fields_form = None

    def get_view_on_site_url(self, obj=None):
        if obj is None or not self.view_on_site:
            return None
        if callable(self.view_on_site):
            return self.view_on_site(obj)
        if not hasattr(obj, "get_absolute_url"):
            return None
        return reverse(
            "sb_admin:view_on_site_redirect",
            kwargs={"view": self.get_id(), "object_id": obj.pk},
            current_app=self.admin_site.name,
        )

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

    def get_dynamic_form_class(self, form):
        if issubclass(form, SBAdminDynamicFormMixin):
            return form
        return type(
            f"SBAdminDynamic{form.__name__}",
            (SBAdminDynamicFormMixin, form),
            {
                "__module__": form.__module__,
            },
        )

    def get_form(self, request, obj=None, **kwargs):
        self.initialize_all_base_fields_form(request)
        form = super().get_form(request, obj, **kwargs)
        form = self.get_dynamic_form_class(form)
        self.initialize_form_class(form, request)
        return form

    def get_sbadmin_fieldsets(
        self, request, object_id=None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        return self.sbadmin_fieldsets or self.fieldsets or []

    def get_fieldsets(
        self, request, obj=None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        sbadmin_fieldsets = self.get_sbadmin_fieldsets(
            request, getattr(obj, "id", None)
        )
        if not sbadmin_fieldsets:
            return super().get_fieldsets(request, obj)
        fieldsets = []
        for fieldset in sbadmin_fieldsets:
            fieldset_dict = {
                "fields": SBAdminDynamicFormMixin.get_fieldset_fields(fieldset[1])
            }
            classes = fieldset[1].get("classes")
            description = fieldset[1].get("description")
            if classes:
                fieldset_dict["classes"] = classes
            if description:
                fieldset_dict["description"] = description
            fieldsets.append((fieldset[0], fieldset_dict))
        return fieldsets

    def get_dynamic_region_object(self, request, modifier):
        if modifier == SBADMIN_DYNAMIC_REGION_ADD_MODIFIER:
            return None
        if hasattr(self, "get_object"):
            return self.get_object(request, modifier)
        try:
            return self.get_queryset(request).get(pk=modifier)
        except self.model.DoesNotExist:
            return None

    def get_dynamic_region_form_class(self, request, obj=None):
        return self.get_form(request, obj=obj, change=bool(obj))

    def get_dynamic_region_form_kwargs(self, request, form_class, data, obj=None):
        form_kwargs = {}
        if obj is not None:
            form_kwargs["instance"] = obj
        prefix = data.get(SBADMIN_DYNAMIC_REGION_PREFIX_PARAM)
        if prefix:
            form_kwargs["prefix"] = prefix
        form_kwargs["initial"] = self._dynamic_region_initial_from_data(
            form_class, data, form_kwargs
        )
        return form_kwargs

    @sbadmin_action
    def sbadmin_dynamic_region(self, request, modifier):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        region_name = request.POST.get(SBADMIN_DYNAMIC_REGION_PARAM)
        if not region_name:
            return HttpResponseBadRequest(f"Missing {SBADMIN_DYNAMIC_REGION_PARAM}.")

        obj = self.get_dynamic_region_object(request, modifier)
        if modifier != SBADMIN_DYNAMIC_REGION_ADD_MODIFIER and obj is None:
            return HttpResponse("", status=404)

        form_class = self.get_dynamic_region_form_class(request, obj)
        data = request.POST
        form_kwargs = self.get_dynamic_region_form_kwargs(
            request, form_class, data, obj
        )
        form = form_class(**form_kwargs)
        region = form.get_dynamic_region(region_name, request)
        if region is None:
            return HttpResponse("", status=404)

        regions = SBAdminDynamicFormMixin.dynamic_regions_for_request(
            form, region, request
        )
        rendered_regions = []
        for target_region in regions:
            rendered_regions.append(
                render_to_string(
                    "sb_admin/includes/dynamic_region.html",
                    {
                        "dynamic_region": form.get_dynamic_region_context(
                            target_region, request, is_fragment=True
                        ),
                    },
                    request=request,
                )
            )
        html = "".join(rendered_regions)
        response = HttpResponse(html)
        trigger_client_event(
            response,
            "sbadminDynamicRegionUpdated",
            {"region": region.name},
        )
        return response

    @staticmethod
    def _dynamic_region_initial_from_data(form_class, data, form_kwargs):
        if form_kwargs is None:
            form_kwargs = {}
        elif not isinstance(form_kwargs, dict):
            obj = form_kwargs
            form_kwargs = {}
            if obj is not None:
                form_kwargs["instance"] = obj
        return dynamic_region_initial_from_data(form_class, data, form_kwargs)

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
        extra_context.update(self.get_change_view_context(request, object_id))
        extra_context.update(self.get_global_context(request, object_id))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request))
        return super().changelist_view(request, extra_context)

    def get_action_url(self, action, modifier="template", object_id=None) -> str:
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs=self.get_action_url_kwargs(action, modifier, object_id),
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

    def full_clean(self):
        # Django treats inline forms with default-only values as unchanged and skips them.
        # During parent creation, for required singleton inlines (min=max=1 with validate_min/max),
        # we can safely mark such forms as changed so the related inline object can be created.
        is_change = getattr(self, "parent_change", True)
        if (
            not is_change
            and self.min_num == 1
            and self.max_num == 1
            and self.validate_min
            and self.validate_max
        ):
            for form in self.forms:
                form.has_changed = lambda: True
        return super().full_clean()


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

    def get_id(self) -> str:
        return self.get_model_path()

    def get_sbadmin_fieldsets(
        self, request, object_id=None
    ) -> list[tuple[str | None, dict[str, Any]]]:
        fieldsets = super().get_sbadmin_fieldsets(request, object_id)
        if fieldsets:
            return fieldsets
        raise ImproperlyConfigured(
            f"{self} is missing definition of fieldsets or sbadmin_fieldsets."
        )

    def _register_form_autocomplete(self, request) -> None:
        try:
            self.get_sbadmin_fieldsets(
                request, getattr(request.request_data, "object_id", None)
            )
        except ImproperlyConfigured:
            return
        self.get_form(request)()

    def _register_inline_autocomplete(self, request) -> None:
        obj = None
        object_id = getattr(request.request_data, "object_id", None)
        if object_id is not None:
            obj = self.get_object(request, object_id)
        for inline in self.get_inline_instances(request, obj=obj):
            inline._register_inline_autocomplete(request)

    def init_actions(self, request) -> None:
        super().init_actions(request)
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        if object_id is None:
            return
        try:
            obj = self.get_object(request, object_id)
        except PermissionDenied:
            return
        inline_instances = self.get_inline_instances(request, obj=obj)
        for inline in inline_instances:
            inline.init_actions(request)

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

    def get_action_url(self, action, modifier="template", object_id=None) -> str:
        if not hasattr(self, action):
            raise ImproperlyConfigured(f"Action {action} does not exist on {self}")
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs=self.get_action_url_kwargs(action, modifier, object_id),
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

    def get_previous_next_context(self, request, object_id) -> dict[str, Any]:
        if not self.sbadmin_previous_next_buttons_enabled or not object_id:
            return {}

        raw_filters = request.GET.get("_changelist_filters", "")
        try:
            all_params = json.loads(
                urllib.parse.parse_qs(urllib.parse.unquote(raw_filters))["params"][0]
            )
        except Exception:
            all_params = {}

        list_action = self.sbadmin_list_action_class(
            self, request, all_params=all_params
        )
        additional_filter = self.get_additional_filter_for_previous_next_context(
            request, object_id
        )

        view_id = self.get_id()
        try:
            page_num = int(list_action.table_params.get(TABLE_PARAMS_PAGE_NAME, 1))
        except (TypeError, ValueError):
            page_num = 1
        page_size = list_action.page_size

        ordering = list(list_action.get_order_by_from_request() or ["pk"])

        # Page window + one row of overhang on each side so prev/next crosses
        # the page boundary without a second query.
        from_item = max(0, (page_num - 1) * page_size - 1)
        to_item = page_num * page_size + 1
        base_qs = list_action.build_final_data_count_queryset(
            additional_filter, apply_plugins=False
        )
        window_pks = list(
            base_qs.order_by(*ordering).values_list("pk", flat=True)[from_item:to_item]
        )

        try:
            current_pk = self.model._meta.pk.to_python(object_id)
            local_idx = window_pks.index(current_pk)
        except (ValidationError, ValueError, TypeError):
            return {}

        def neighbor_url(target_idx):
            if not 0 <= target_idx < len(window_pks):
                return None
            target_page = (from_item + target_idx) // page_size + 1
            view_params = all_params.get(view_id, {})
            new_all_params = {
                **all_params,
                view_id: {
                    **view_params,
                    TABLE_PARAMS_NAME: {
                        **view_params.get(TABLE_PARAMS_NAME, {}),
                        TABLE_PARAMS_PAGE_NAME: target_page,
                    },
                },
            }
            new_filters = urllib.parse.urlencode({"params": json.dumps(new_all_params)})
            return f"{self.get_detail_url(window_pks[target_idx])}?_changelist_filters={new_filters}"

        return {
            "previous_url": neighbor_url(local_idx - 1),
            "next_url": neighbor_url(local_idx + 1),
            "current_index": from_item + local_idx + 1,
            "all_objects_count": base_qs.count(),
        }

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_global_context(request, None))
        extra_context.update(self.get_tabs_context(request, None))
        return self.changeform_view(request, None, form_url, extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self.get_change_view_context(request, object_id))
        extra_context.update(self.get_global_context(request, object_id))
        extra_context.update(self.get_tabs_context(request, object_id))
        extra_context.update(self.get_previous_next_context(request, object_id))
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        return self.action_list(request, extra_context=extra_context)

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if context.get("sbadmin_is_modal"):
            media = context["media"]
            js_assets = [str(asset) for asset in getattr(media, "_js", [])]
            media_json = {
                "js": js_assets,
                "css": {
                    medium: [str(path) for path in paths]
                    for medium, paths in getattr(media, "_css", {}).items()
                },
            }
            context["media_json"] = media_json
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

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

            if "django_smartbase_admin.audit" in settings.INSTALLED_APPS:
                return redirect_to_audit_history(request, obj)

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
                "reload": request.POST.get(SBADMIN_RELOAD_ON_SAVE_VAR) == "1",
            },
        )
        trigger_client_event(response, "hideModal", {"elt": "sb-admin-modal"})
        return response

    def build_action_response(
        self, request, *, reload_table=True, hide_modal=False
    ) -> HttpResponse:
        response = HttpResponse(render_notifications(request))
        if hide_modal:
            trigger_client_event(response, "hideModal", {})
        if reload_table:
            trigger_client_event(response, TABLE_RELOAD_DATA_EVENT_NAME, {})
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
        from django_smartbase_admin.admin.site import sb_admin_site

        parent_path = request.POST.get(SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR)
        parent_pk = request.POST.get(SBADMIN_PARENT_INSTANCE_PK_VAR)
        if not (parent_path and parent_pk):
            return

        # Token: ``modal_<app>_<model>_<field>_<parent_model>``; rsplit
        # tolerates underscores in app labels / model names.
        try:
            _, _, app_label, model_name = parent_path.rsplit("_", 3)
            content_type = ContentType.objects.get(
                app_label=app_label, model=model_name
            )
            parent_model = content_type.model_class()
        except (ValueError, ContentType.DoesNotExist):
            raise PermissionDenied

        # Route through the registered parent admin so has_view_permission
        # and restrict_queryset gate the lookup.
        parent_admin = sb_admin_site._registry.get(parent_model)
        if (
            parent_admin is None
            or not parent_admin.has_view_permission(request)
            or not parent_admin.get_queryset(request).filter(pk=parent_pk).exists()
        ):
            raise PermissionDenied

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
    validate_min = False
    validate_max = False

    def get_instance_label(self, request, obj: Model | None = None) -> str | None:
        if obj:
            return str(obj)
        return None

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

    def get_sbadmin_inline_list_actions_processed(self, request) -> list:
        object_id = (
            self.parent_instance.pk
            if self.parent_instance is not None and self.parent_instance.pk is not None
            else None
        )
        return self.process_inline_actions(
            request,
            self._bind_parent_row_action_modals(
                self.get_sbadmin_inline_list_actions(request)
            ),
            object_id=object_id,
        )

    def init_actions(self, request) -> None:
        # inline supports only own sbadmin_inline_list_actions but also sbadmin_fieldsets_actions
        object_id = (
            self.parent_instance.pk
            if self.parent_instance is not None and self.parent_instance.pk is not None
            else None
        )
        all_actions = [*self.get_sbadmin_inline_list_actions_processed(request)]
        if object_id is not None:
            all_actions.extend(
                self.get_sbadmin_fieldsets_actions_processed(request, object_id)
            )
        self.register_action_autocomplete_views(request, all_actions)

    def _bind_parent_row_action_modals(self, actions: list) -> list:
        if self.parent_instance is None:
            return actions
        parent_admin = self.admin_site._registry.get(self.parent_model)
        if parent_admin is None:
            return actions
        return [
            self._bind_parent_row_action_modal(action, parent_admin)
            for action in actions
        ]

    def _bind_parent_row_action_modal(self, action, parent_admin):
        # we need to add view on action to be parent_admin
        # this ->
        #         SBAdminFormViewAction(
        #             title=_("Úprava kreditu"),
        #             target_view=UserManualCreditView,
        #             open_in_modal=True,
        #             css_class="btn btn-primary",
        #         )
        # needs to become ->
        #         SBAdminFormViewAction(
        #             ...
        #             view=parent_admin
        #             ...
        #         )
        sub_actions = getattr(action, "sub_actions", None)
        if sub_actions:
            resolved_sub_actions = [
                self._bind_parent_row_action_modal(sub_action, parent_admin)
                for sub_action in sub_actions
            ]
            if resolved_sub_actions != sub_actions:
                action = copy(action)
                action.sub_actions = resolved_sub_actions
            return action
        if getattr(action, "view", None) is not None:
            return action
        target_view = getattr(action, "target_view", None)
        if target_view is None:
            return action
        from django_smartbase_admin.engine.modal_view import RowActionModalView

        try:
            is_row_action_modal = issubclass(target_view, RowActionModalView)
        except TypeError:
            is_row_action_modal = False
        if not is_row_action_modal:
            return action
        action = copy(action)
        action.view = parent_admin
        return action

    def get_action_url(self, action, modifier="template", object_id=None) -> str:
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs=self.get_action_url_kwargs(action, modifier, object_id),
        )

    def _register_inline_autocomplete(self, request) -> None:
        form_class = self.get_formset(
            request, getattr(self, "parent_instance", None)
        ).form
        self.initialize_form_class(form_class, request)
        form_class()

    def get_parent_instance_from_request(self):
        # Try to get parent instance from request referrer
        request = (
            getattr(self, "threadsafe_request", None)
            or SBAdminThreadLocalService.get_request()
        )
        allowed = SBAdminViewService.has_permission(
            request=request, model=self.parent_model, permission="view"
        )
        if not allowed:
            return None

        referer = request.META.get("HTTP_REFERER")
        if not referer:
            return None
        resolved = resolve(urlparse(referer).path)
        # Try common kwargs for object ID
        object_id = resolved.kwargs.get("object_id")
        if not object_id:
            return None
        base_qs = SBAdminViewService.get_restricted_queryset(
            self.parent_model, request, request.request_data
        )
        return base_qs.get(pk=object_id)

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
            "inline_list_actions": self.get_sbadmin_inline_list_actions_processed(
                request
            ),
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

    def get_dynamic_region_form_class(self, request, obj=None):
        return self.get_formset(request, None).form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == self.sortable_field_name:
            formfield.widget = HiddenInput()
        return formfield

    def get_formset(self, request, obj=None, **kwargs):
        self.initialize_all_base_fields_form(request)
        kwargs.update(validate_min=self.validate_min, validate_max=self.validate_max)
        formset = super().get_formset(request, obj, **kwargs)
        formset.parent_change = bool(obj)
        form_class = formset.form
        form_class = self.get_dynamic_form_class(form_class)
        self.initialize_form_class(form_class, request)
        formset.form = form_class
        return formset

    # Restricted inline-data batch read (used by MCP) lives in
    # ``django_smartbase_admin.mcp.service.SBAdminMCPDetailService`` so the
    # API-only plumbing stays out of normal admin flow.


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


class SBAdminStackedInlineBase(SBAdminInline):
    default_collapsed = False

    def get_sbadmin_default_collapsed(self, request):
        return self.default_collapsed

    def get_context_data(self, request) -> dict[str, Any]:
        context_data = super().get_context_data(request)
        context_data["default_collapsed"] = self.get_sbadmin_default_collapsed(request)
        return context_data

    def get_sbadmin_inline_list_actions(self, request) -> list:
        actions = super().get_sbadmin_inline_list_actions(request)
        actions.append(
            SBAdminCustomAction(
                title="Collapse",
                css_class=f"collapse-all-stacked-inlines {'collapsed' if self.get_sbadmin_default_collapsed(request) else ''}",
                url=request.get_full_path(),
            )
        )
        return actions


class SBAdminStackedInline(SBAdminStackedInlineBase, NestedStackedInline):
    template = "sb_admin/inlines/stacked_inline.html"
    fieldset_template = "sb_admin/includes/inline_fieldset.html"
    formset = SBAdminNestedInlineFormSet


class SBAdminGenericStackedInline(SBAdminStackedInlineBase, NestedGenericStackedInline):
    template = "sb_admin/inlines/stacked_inline.html"
    fieldset_template = "sb_admin/includes/inline_fieldset.html"
    formset = SBAdminGenericInlineFormSet


if parler_enabled:

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
