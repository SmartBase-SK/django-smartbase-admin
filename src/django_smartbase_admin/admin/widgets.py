import json
import logging
import sys

from ckeditor.widgets import CKEditorWidget
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from django import forms
from django.conf import settings
from django.contrib.admin.widgets import (
    AdminURLFieldWidget,
    ForeignKeyRawIdWidget,
)
from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.contrib.postgres.forms import RangeWidget
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    ValidationError,
)
from django.db.models import ForeignKey, OneToOneField
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import get_format
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _, get_language
from django.views.generic.base import ContextMixin
from filer.fields.file import AdminFileWidget as FilerAdminFileWidget
from filer.fields.image import AdminImageWidget
from filer.models import File

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_PARENT_INSTANCE_PK_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
)
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    SBAdminTreeWidgetMixin,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.templatetags.sb_admin_tags import (
    SBAdminJSONEncoder,
)
from django_smartbase_admin.utils import is_modal, convert_django_to_flatpickr_format

try:
    # Django >= 5.0
    from django.contrib.admin.exceptions import NotRegistered
except ImportError:
    from django.contrib.admin.sites import NotRegistered

logger = logging.getLogger(__name__)


def get_datetime_placeholder(lang=None):
    lang = lang or get_language()
    sb_admin_settings = getattr(settings, "SB_ADMIN_SETTINGS", {})
    placeholder_setting = sb_admin_settings.get("DATETIME_PLACEHOLDER", {})
    return placeholder_setting.get(
        lang,
        placeholder_setting.get("default", {"date": "mm.dd.yyyy", "time": "hh:mm"}),
    )


class SBAdminBaseWidget(ContextMixin):
    sb_admin_widget = True

    def __init__(self, form_field=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_field = form_field

    def init_widget_dynamic(self, form, form_field, field_name, view, request):
        self.form_field = form_field

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["form_field"] = self.form_field
        opts = None

        if self.form_field:
            view = getattr(self.form_field, "view", None)
            if view:
                if hasattr(view, "opts"):
                    opts = view.opts
                elif hasattr(view, "view") and hasattr(view.view, "opts"):
                    opts = view.view.opts

        if opts:
            modal_prefix = ""
            try:
                modal_prefix = (
                    "modal_"
                    if is_modal(SBAdminThreadLocalService.get_request())
                    else ""
                )
            except:
                pass
            widget_id = f"{modal_prefix}{opts.app_label}_{opts.model_name}_{context['widget']['attrs']['id']}"
            context["widget"]["attrs"]["id"] = widget_id
            # needed for BoundField.id_for_label to work correctly
            self.attrs["id"] = widget_id
        return context


class SBAdminTextInputWidget(SBAdminBaseWidget, forms.TextInput):
    template_name = "sb_admin/widgets/text.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminPasswordInputWidget(SBAdminBaseWidget, forms.PasswordInput):
    template_name = "sb_admin/widgets/password.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminTextareaWidget(SBAdminBaseWidget, forms.Textarea):
    template_name = "sb_admin/widgets/textarea.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminEmailInputWidget(SBAdminBaseWidget, forms.EmailInput):
    template_name = "sb_admin/widgets/email.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminURLFieldWidget(SBAdminBaseWidget, AdminURLFieldWidget):
    template_name = "sb_admin/widgets/url.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminNumberWidget(SBAdminBaseWidget, forms.NumberInput):
    class_name = "input"
    template_name = "sb_admin/widgets/number.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": self.class_name, **(attrs or {})})


class SBAdminCheckboxWidget(SBAdminBaseWidget, forms.CheckboxInput):
    template_name = "sb_admin/widgets/checkbox.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "checkbox", **(attrs or {})})


class SBAdminToggleWidget(SBAdminBaseWidget, forms.CheckboxInput):
    template_name = "sb_admin/widgets/toggle.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "toggle", **(attrs or {})})


class SBAdminCKEditorWidget(SBAdminBaseWidget, CKEditorWidget):

    def __init__(
        self,
        config_name="default",
        extra_plugins=None,
        external_plugin_resources=None,
        form_field=None,
        attrs=None,
    ):
        super().__init__(
            form_field,
            template_name="sb_admin/widgets/ckeditor.html",
            attrs=attrs,
            config_name=config_name,
            extra_plugins=extra_plugins,
            external_plugin_resources=external_plugin_resources,
        )


class SBAdminCKEditorUploadingWidget(CKEditorUploadingWidget, SBAdminCKEditorWidget):
    pass


class SBAdminSelectWidget(SBAdminBaseWidget, forms.Select):
    template_name = "sb_admin/widgets/select.html"
    option_template_name = "sb_admin/widgets/select_option.html"

    def __init__(self, form_field=None, attrs=None, choices=()):
        super().__init__(
            form_field, attrs={"class": "input", **(attrs or {})}, choices=choices
        )


class SBAdminRadioWidget(SBAdminBaseWidget, forms.RadioSelect):
    template_name = "sb_admin/widgets/radio.html"
    option_template_name = "sb_admin/widgets/radio_option.html"

    def __init__(self, form_field=None, attrs=None, choices=()):
        super().__init__(
            form_field, attrs={"class": "radio", **(attrs or {})}, choices=choices
        )


class SBAdminRadioDropdownWidget(SBAdminBaseWidget, forms.RadioSelect):
    template_name = "sb_admin/widgets/radio_dropdown.html"
    option_template_name = "sb_admin/widgets/radio_option.html"

    def __init__(self, form_field=None, attrs=None, choices=()):
        super().__init__(
            form_field,
            attrs={"class": "radio radio-list", **(attrs or {})},
            choices=choices,
        )


class SBAdminMultipleChoiceWidget(SBAdminBaseWidget, forms.CheckboxSelectMultiple):
    template_name = "sb_admin/widgets/checkbox_dropdown.html"
    option_template_name = "sb_admin/widgets/checkbox_option.html"

    def __init__(self, form_field=None, attrs=None, choices=()):
        super().__init__(
            form_field,
            choices=choices,
            attrs={"class": "checkbox", **(attrs or {})},
        )


class SBAdminMultipleChoiceInlineWidget(SBAdminMultipleChoiceWidget):
    template_name = "sb_admin/widgets/checkbox_group.html"
    option_template_name = "sb_admin/widgets/checkbox.html"


class SBAdminNullBooleanSelectWidget(SBAdminBaseWidget, forms.NullBooleanSelect):
    template_name = "sb_admin/widgets/select.html"
    option_template_name = "sb_admin/widgets/select_option.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminDateWidget(SBAdminBaseWidget, forms.DateInput):
    template_name = "sb_admin/widgets/date.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field,
            format="%Y-%m-%d",
            attrs={
                "class": "input js-datepicker",
                "data-sbadmin-datepicker": self.get_data(),
                "placeholder": get_datetime_placeholder()["date"],
                **(attrs or {}),
            },
        )

    def get_data(self):
        return json.dumps(
            {
                "flatpickrOptions": {
                    "dateFormat": "Y-m-d",
                    "altInput": True,
                    "altFormat": convert_django_to_flatpickr_format(
                        get_format("SHORT_DATE_FORMAT")
                    ),
                },
            },
            cls=SBAdminJSONEncoder,
        )


class SBAdminTimeWidget(SBAdminBaseWidget, forms.TimeInput):
    template_name = "sb_admin/widgets/time.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field,
            attrs={
                "class": "input js-timepicker",
                "placeholder": get_datetime_placeholder()["time"],
                "autocomplete": "do-not-autofill",
                **(attrs or {}),
            },
        )


class SBAdminDateTimeWidget(SBAdminBaseWidget, forms.DateTimeInput):
    template_name = "sb_admin/widgets/datetime.html"

    def __init__(self, form_field=None, attrs=None, format=None):
        super().__init__(
            form_field,
            format="%Y-%m-%d %H:%M",
            attrs={
                "class": "input js-datetimepicker",
                "data-sbadmin-datepicker": self.get_data(),
                "placeholder": get_datetime_placeholder()["date"],
                **(attrs or {}),
            },
        )

    def get_data(self):
        return json.dumps(
            {
                "flatpickrOptions": {
                    "dateFormat": "Y-m-d H:i",
                    "altInput": True,
                    "altFormat": convert_django_to_flatpickr_format(
                        get_format("SHORT_DATETIME_FORMAT")
                    ),
                },
            },
            cls=SBAdminJSONEncoder,
        )


class SBAdminSplitDateTimeWidget(SBAdminBaseWidget, forms.SplitDateTimeWidget):
    template_name = "sb_admin/widgets/splitdatetime.html"

    def __init__(self, form_field=None, attrs=None):
        self.form_field = form_field
        widgets = [SBAdminDateWidget, SBAdminTimeWidget]
        # init of forms.MultiWidget with form_field attribute during widget instancing
        if isinstance(widgets, dict):
            self.widgets_names = [("_%s" % name) if name else "" for name in widgets]
            widgets = widgets.values()
        else:
            self.widgets_names = ["_%s" % i for i in range(len(widgets))]
        self.widgets = [w(form_field) if isinstance(w, type) else w for w in widgets]
        forms.Widget.__init__(self, attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["form_field"] = self.form_field
        return context


class SBAdminArrayWidget(SBAdminTextInputWidget):
    template_name = "sb_admin/widgets/array.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context.get("widget", None)
        array_widgets = []
        template_widget = {"attrs": {"class": "input"}}
        if widget:
            value = widget.get("value")
            if value:
                value_array = value.split(self.form_field.delimiter)
                array_widgets = [
                    {"value": value, **template_widget} for value in value_array
                ]
        context["array_widgets"] = array_widgets
        context["template_widget"] = template_widget
        return context


class SBAdminAttributesWidget(SBAdminTextInputWidget):
    template_name = "sb_admin/widgets/attributes.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context.get("widget", None)
        dict_widgets = []
        template_widget = {"attrs": {"class": "input"}}
        if widget and value:
            if isinstance(value, str):
                value = json.loads(value)
            dict_widgets = [
                {
                    "key": {"value": key, **template_widget},
                    "value": {"value": value, **template_widget},
                }
                for key, value in value.items()
            ]
        context["dict_widgets"] = dict_widgets
        context["template_widget"] = template_widget
        return context


class SBAdminAutocompleteWidget(
    SBAdminBaseWidget, AutocompleteFilterWidget, forms.Widget
):
    template_name = "sb_admin/widgets/autocomplete.html"
    view = None
    form = None
    field_name = None
    initialised = None
    allow_add = None
    create_value_field = None
    default_create_data = None
    forward_to_create = None
    reload_on_save = None
    REQUEST_CREATED_DATA_KEY = "autocomplete_created_data"

    def __init__(self, form_field=None, *args, **kwargs):
        attrs = kwargs.pop("attrs", None)
        self.reload_on_save = kwargs.pop("reload_on_save", False)
        self.allow_add = kwargs.pop("allow_add", None)
        self.create_value_field = kwargs.pop("create_value_field", None)
        self.forward_to_create = kwargs.pop("forward_to_create", [])
        super().__init__(form_field, *args, **kwargs)
        self.attrs = {} if attrs is None else attrs.copy()
        if self.multiselect and self.allow_add:
            raise ImproperlyConfigured(
                "Multiselect with creation is currently not supported."
            )

    def get_id(self):
        base_id = super().get_id()
        if self.form:
            base_id += f"_{self.form.__class__.__name__}"
        return base_id

    def init_widget_dynamic(
        self, form, form_field, field_name, view, request, default_create_data=None
    ):
        super().init_widget_dynamic(form, form_field, field_name, view, request)
        if self.initialised:
            return
        self.initialised = True
        self.field_name = field_name
        self.view = view
        self.form = form
        self.default_create_data = default_create_data or {}
        self.init_autocomplete_widget_static(
            self.field_name,
            self.model,
            request.request_data.configuration,
        )

    def get_field_name(self):
        return self.field_name

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        self.input_id = (
            context["widget"]["attrs"]["id"] or f'id_{context["widget"]["name"]}'
        )

        context["widget"]["type"] = "hidden"
        context["widget"]["attrs"]["id"] = self.input_id
        context["widget"]["attrs"]["class"] = "js-autocomplete-detail"
        context["widget"]["attrs"]["data-empty-label"] = (
            getattr(self.form_field, "empty_label", "---------") or "---------"
        )
        query_suffix = "__in"
        threadsafe_request = SBAdminThreadLocalService.get_request()
        if not self.is_multiselect():
            query_suffix = ""
            self.multiselect = False
        context["widget"]["attrs"]["preselect_field"] = threadsafe_request.GET.get(
            "sbadmin_parent_instance_field"
        )
        context["widget"]["attrs"]["preselect_field_label"] = (
            threadsafe_request.GET.get(SBADMIN_PARENT_INSTANCE_LABEL_VAR)
        )
        context["widget"]["attrs"]["preselect_field_value"] = (
            threadsafe_request.GET.get(SBADMIN_PARENT_INSTANCE_PK_VAR)
        )
        parsed_value = None
        if value:
            parsed_value = self.parse_value_from_input(threadsafe_request, value)
            is_create = self.parse_is_create_from_input(
                threadsafe_request,
                threadsafe_request.request_data.request_post.get(name),
            )
            selected_options = []
            if is_create:
                errors = getattr(self.form, "errors", {})
                if errors.get(self.field_name):
                    parsed_value = None
            if parsed_value:
                if self.is_multiselect() and not isinstance(parsed_value, list):
                    parsed_value = [parsed_value]

                try:
                    for item in self.get_queryset(threadsafe_request).filter(
                        **{f"{self.get_value_field()}{query_suffix}": parsed_value}
                    ):
                        selected_options.append(
                            {
                                "value": self.get_value(threadsafe_request, item),
                                "label": self.get_label(threadsafe_request, item),
                            }
                        )
                except ValueError as e:
                    new_object_id = threadsafe_request.request_data.additional_data.get(
                        self.REQUEST_CREATED_DATA_KEY, {}
                    ).get(self.field_name)
                    if new_object_id:
                        selected_options.append(
                            {
                                "value": new_object_id,
                                "label": value,
                            }
                        )
                    elif hasattr(self.form, "add_error"):
                        self.form.add_error(
                            self.field_name,
                            _(
                                "The new value was created but became unselected due to another validation error. Please select it again."
                            ),
                        )

            context["widget"]["value"] = json.dumps(selected_options)
            context["widget"]["value_list"] = selected_options

        if (
            threadsafe_request.request_data.configuration.autocomplete_show_related_buttons(
                self.model,
                field_name=self.field_name,
                current_view=self.view,
                request=threadsafe_request,
            )
            and not self.is_multiselect()
        ):
            self.add_related_buttons_urls(parsed_value, threadsafe_request, context)
            context["reload_on_save"] = self.reload_on_save

        return context

    def add_related_buttons_urls(self, parsed_value, request, context):
        try:
            if hasattr(sb_admin_site, "get_model_admin"):
                # Django >= 5.0
                related_model_admin = sb_admin_site.get_model_admin(self.model)
            else:
                related_model_admin = sb_admin_site._registry.get(self.model)
                if not related_model_admin:
                    return
            if parsed_value and related_model_admin.has_view_or_change_permission(
                request
            ):
                context["widget"]["attrs"]["related_edit_url"] = (
                    related_model_admin.get_detail_url(parsed_value)
                )
            if related_model_admin.has_add_permission(request):
                context["widget"]["attrs"]["related_add_url"] = (
                    related_model_admin.get_new_url(request)
                )
        except NotRegistered:
            pass

    def is_multiselect(self):
        if self.multiselect is not None:
            return self.multiselect
        model_field = getattr(self.field, "model_field", None)
        return not (model_field and (model_field.one_to_one or model_field.many_to_one))

    def _is_in_validation_context(self):
        """
        Check if value_from_datadict is being called during form validation
        (full_clean, _clean_fields, etc.) vs. during change detection by formsets.

        Returns True if called during actual validation, False if called during
        change detection or other non-validation contexts.

        Uses sys._getframe() instead of inspect.currentframe() for better performance,
        as this method is called frequently during form processing.
        """
        # Get the call stack - using sys._getframe() for better performance
        # sys._getframe(1) gets the caller's frame (skipping this method)
        try:
            current_frame = sys._getframe(1)
        except ValueError:
            # Fallback if _getframe is not available (unlikely in CPython)
            return False

        # Look for validation-related methods in the call stack
        validation_methods = {
            "_clean_bound_field",
        }

        # Walk up the call stack
        depth = 0
        while current_frame and depth < 5:  # Limit depth to avoid infinite loops
            method_name = current_frame.f_code.co_name
            if method_name in validation_methods:
                return True
            current_frame = current_frame.f_back
            depth += 1

        return False

    def get_forward_data(self, request, name):
        """
        Parse forward data from request.request_data.request_post.

        For each field in self.forward, use name as base field name and replace
        in it current field name with forward field name, return dict.

        Args:
            request: The request object
            name: The base field name (e.g., "product__category")

        Returns:
            dict: Forward data with keys being forward field names and values
                  from request data
        """
        forward_data = {}
        if not getattr(self, "forward", None):
            return forward_data

        post_data = getattr(request.request_data, "request_post", {})
        if not post_data:
            return forward_data

        # For each field in self.forward list
        for forward_field in self.forward:
            # Replace only from end of name, separated by last -
            # Example: if name="prefix-field_name", self.field_name="field_name",
            # forward_field="parent" -> result="prefix-parent"
            name_parts = name.split("-")

            # Replace only if the last part matches self.field_name
            if name_parts and name_parts[-1] == self.field_name:
                # Replace the last part with forward_field and join back
                name_parts[-1] = forward_field
                forward_field_name = "-".join(name_parts)
            else:
                # If last part doesn't match, don't create forward field name
                continue

            # Get value from post_data if it exists
            if forward_field_name in post_data:
                forward_data[forward_field] = post_data.get(forward_field_name)

        return forward_data

    def get_forward_data_to_create(self, request, forward_data):
        forward_data_to_create = {}
        for field_name in self.forward_to_create:
            value = forward_data.get(field_name)
            if value is None:
                continue
            # If forwarding a FK value from the parent form (e.g. for dependent dropdowns),
            # store it under `<field>_id` so `Model(**kwargs)` accepts the raw PK.
            store_key = field_name
            form_model = getattr(getattr(self, "form", None), "model", None)
            if form_model is not None:
                try:
                    form_model_field = form_model._meta.get_field(field_name)
                except FieldDoesNotExist:
                    form_model_field = None
                if isinstance(form_model_field, (ForeignKey, OneToOneField)):
                    store_key = form_model_field.attname

            forward_data_to_create[store_key] = self.parse_value_from_input(
                request, value
            )
            if not self.is_multiselect():
                forward_data_to_create[store_key] = next(
                    iter(forward_data_to_create[store_key]), None
                )

        return forward_data_to_create

    def value_from_datadict(self, data, files, name):
        input_value = super().value_from_datadict(data, files, name)
        threadsafe_request = SBAdminThreadLocalService.get_request()
        parsed_value = self.parse_value_from_input(threadsafe_request, input_value)
        if parsed_value is None:
            return parsed_value

        if not self.is_multiselect():
            parsed_value = next(iter(parsed_value), None)

        # Only perform validation during actual form cleaning, not during change detection
        # by inline formsets or during HTML rendering
        is_in_validation = self._is_in_validation_context()
        if is_in_validation:
            try:
                has_changed = self.form_field.has_changed(
                    self.form.initial.get(self.field_name, None), parsed_value
                )
            except AttributeError:
                has_changed = False
            if has_changed:
                parsed_is_create = self.parse_is_create_from_input(
                    threadsafe_request, input_value
                )
                if not self.is_multiselect():
                    parsed_is_create = next(iter(parsed_is_create), None)
                base_qs = self.get_queryset(threadsafe_request)
                forward_data = self.get_forward_data(threadsafe_request, name)
                qs = self.filter_search_queryset(
                    threadsafe_request,
                    base_qs,
                    forward_data=forward_data,
                )
                self.form_field.queryset = qs
                parsed_value = self.validate(
                    parsed_value,
                    qs,
                    threadsafe_request,
                    forward_data,
                    parsed_is_create,
                )

        return parsed_value

    def should_create_new_obj(self):
        return self.allow_add and self.create_value_field

    def create_new_obj(self, value, queryset, request, forward_data):
        if isinstance(value, list):
            # TODO: multiselect creation
            return self.form_field.to_python(value)
        else:
            forward_data_to_create = self.get_forward_data_to_create(
                request, forward_data
            )
            data_to_create = {
                self.create_value_field: value,
                **self.default_create_data,
                **forward_data_to_create,
            }
            new_obj = queryset.model.objects.create(**data_to_create)
            try:
                return self.form_field.to_python(new_obj.id)
            except ValidationError:
                new_obj.delete()
                raise ValidationError(
                    self.form_field.error_messages["invalid_choice"],
                    code="invalid_choice",
                    params={"value": value},
                )

    def validate(self, value, queryset, request, forward_data, is_create=False):
        is_create_value = (
            True in is_create if isinstance(is_create, list) else is_create
        )
        if is_create_value and self.should_create_new_obj():
            new_object = self.create_new_obj(value, queryset, request, forward_data)
            request.request_data.additional_data[self.REQUEST_CREATED_DATA_KEY] = (
                request.request_data.additional_data.get(
                    self.REQUEST_CREATED_DATA_KEY, {}
                )
            )
            request.request_data.additional_data[self.REQUEST_CREATED_DATA_KEY][
                self.field_name
            ] = new_object.pk
            return new_object
        return self.form_field.to_python(value)

    @classmethod
    def apply_to_model_field(cls, model_field):
        return None


class SBAdminAutocompleteMultiselectWidget(SBAdminAutocompleteWidget):
    multiselect = True


class SBAdminFileWidget(SBAdminBaseWidget, forms.ClearableFileInput):
    template_name = "sb_admin/widgets/clearable_file_input.html"
    clear_checkbox_label = _("Clear")
    initial_text = _("Currently")
    input_text = _("Change file")


class SBAdminImageWidget(SBAdminBaseWidget, AdminImageWidget):
    def __init__(self, form_field=None, *args, **kwargs):
        self.form_field = form_field
        super(AdminImageWidget, self).__init__(
            form_field.rel, form_field.view.admin_site
        )


class SBAdminFilerFileWidget(SBAdminBaseWidget, FilerAdminFileWidget):
    def __init__(self, form_field=None, *args, **kwargs):
        self.form_field = form_field
        super(FilerAdminFileWidget, self).__init__(
            form_field.rel, form_field.view.admin_site, *args, **kwargs
        )

    def render(self, name, value, attrs=None, renderer=None):
        obj = self.obj_for_value(value)
        css_id = attrs.get("id", "id_image_x")
        related_url = None
        change_url = ""
        if value:
            try:
                file_obj = File.objects.get(pk=value)
                if file_obj.logical_folder.is_root:
                    related_url = reverse("sb_admin:filer-directory_listing-root")
                else:
                    related_url = reverse(
                        "sb_admin:filer-directory_listing",
                        args=(file_obj.logical_folder.id,),
                    )
                change_url = reverse(
                    "sb_admin:{}_{}_change".format(
                        file_obj._meta.app_label,
                        file_obj._meta.model_name,
                    ),
                    args=(file_obj.pk,),
                )
            except Exception as e:
                # catch exception and manage it. We can re-raise it for debugging
                # purposes and/or just logging it, provided user configured
                # proper logging configuration
                if settings.FILER_ENABLE_LOGGING:
                    logger.error("Error while rendering file widget: %s", e)
                if settings.FILER_DEBUG:
                    raise
        if not related_url:
            related_url = reverse("sb_admin:filer-directory_listing-last")
        params = self.url_parameters()
        params["_pick"] = "file"
        if params:
            lookup_url = "?" + urlencode(sorted(params.items()))
        else:
            lookup_url = ""
        if "class" not in attrs:
            # The JavaScript looks for this hook.
            attrs["class"] = "vForeignKeyRawIdAdminField"
        # rendering the super for ForeignKeyRawIdWidget on purpose here because
        # we only need the input and none of the other stuff that
        # ForeignKeyRawIdWidget adds
        hidden_input = super(ForeignKeyRawIdWidget, self).render(
            name, value, attrs
        )  # grandparent super
        context = {
            "hidden_input": hidden_input,
            "lookup_url": "{}{}".format(related_url, lookup_url),
            "change_url": change_url,
            "object": obj,
            "lookup_name": name,
            "id": css_id,
            "admin_icon_delete": "admin/img/icon-deletelink.svg",
        }
        # using template name directly to prevent override of template_name
        # when calling render of ForeignKeyRawIdWidget
        html = render_to_string("sb_admin/widgets/filer_file.html", context)
        return mark_safe(html)


class SBAdminReadOnlyPasswordHashWidget(SBAdminBaseWidget, ReadOnlyPasswordHashWidget):
    template_name = "sb_admin/widgets/read_only_password_hash.html"


class SBAdminHiddenWidget(SBAdminBaseWidget, forms.Widget):
    template_name = "sb_admin/widgets/hidden.html"
    input_type = "hidden"


class SBAdminCodeWidget(SBAdminBaseWidget, forms.Widget):
    template_name = "sb_admin/widgets/code.html"
    input_type = "text"

    def __init__(self, form_field=None, *args, **kwargs):
        super().__init__(form_field, *args, **kwargs)
        self.attrs = {
            "code-mirror-options": json.dumps(
                {
                    "mode": "django",
                    "theme": "dracula",
                    "lineWrapping": "true",
                }
            ),
            "code-mirror-width": "100%",
            "code-mirror-height": "300",
        } | self.attrs

    class Media:
        css = {
            "all": [
                "sb_admin/css/codemirror/codemirror.min.css",
                "sb_admin/css/codemirror/dracula.min.css",
            ],
        }
        js = [
            "sb_admin/js/codemirror/codemirror.min.js",
            "sb_admin/js/codemirror/overlay.min.js",
            "sb_admin/js/codemirror/django.min.js",
            "sb_admin/src/js/code.js",
        ]


class SBAdminHTMLWidget(SBAdminBaseWidget, forms.Widget):
    template_name = "sb_admin/widgets/html_read_only.html"


class SBAdminColorWidget(SBAdminTextInputWidget):
    template_name = "sb_admin/widgets/color_field.html"
    color_swatches = getattr(
        settings,
        "SB_ADMIN_COLOR_SWATCHES",
        [
            "#ffbe76",
            "#f9ca24",
            "#f0932b",
            "#ff7979",
            "#eb4d4b",
            "#badc58",
            "#6ab04c",
            "#c7ecee",
            "#7ed6df",
            "#22a6b3",
            "#e056fd",
            "#be2edd",
            "#686de0",
            "#4834d4",
            "#30336b",
            "#130f40",
            "#95afc0",
            "#535c68",
        ],
    )

    class Media:
        css = {
            "all": [
                "sb_admin/css/coloris/coloris.min.css",
            ],
        }
        js = [
            "sb_admin/js/coloris/coloris.min.js",
        ]


class SBAdminTreeWidget(SBAdminTreeWidgetMixin, SBAdminAutocompleteWidget):
    template_name = "sb_admin/widgets/tree_select.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["raw_value"] = value
        context["widget"]["relationship_pick_mode"] = self.relationship_pick_mode
        context["widget"]["value_dict"] = {
            item["value"]: item["label"]
            for item in context["widget"].get("value_list", [])
        }
        context["widget"]["additional_columns"] = self.additional_columns
        context["widget"]["tree_strings"] = self.tree_strings
        context["fancytree_filter_settings"] = {}
        return context

    @classmethod
    def get_descendants_from_tree_data(cls, tree_data, parent_id):
        parent_item = cls.find_parent_in_tree_data(tree_data, parent_id)
        descendants = cls.get_descendats_from_item(parent_item)
        return descendants

    @classmethod
    def get_descendats_from_item(cls, item):
        descendants = []
        if not item:
            return descendants
        for child in item.get("children", []):
            descendants.append(child)
            descendants.extend(cls.get_descendats_from_item(child))
        return descendants

    @classmethod
    def find_parent_in_tree_data(cls, tree_data, parent_id):
        str_parent_id = str(parent_id)
        for item in tree_data:
            if item["key"] == str_parent_id:
                return item
            parent = cls.find_parent_in_tree_data(
                item.get("children", []), str_parent_id
            )
            if parent:
                return parent
        return None

    def value_from_datadict(self, data, files, name):
        input_value = data.get(name)
        threadsafe_request = SBAdminThreadLocalService.get_request()
        parsed_value = self.parse_value_from_input(threadsafe_request, input_value)
        obj = self.form.instance
        if (
            obj
            and parsed_value
            and self.relationship_pick_mode == self.RELATIONSHIP_PICK_MODE_PARENT
        ):
            if obj.id == parsed_value:
                raise ValidationError(_("Cannot set parent to itself"))
            qs = self.get_queryset(threadsafe_request).order_by(*self.order_by)
            tree_data = self.format_tree_data(threadsafe_request, qs)
            children = self.get_descendants_from_tree_data(tree_data, obj.id)
            children_ids = []
            for child in children:
                children_ids.append(child.get("key"))
            if input_value in children_ids:
                raise ValidationError(_("Cannot set parent to it's own child"))
        return parsed_value


class SBAdminDateTimeRangeWidget(SBAdminBaseWidget, RangeWidget):
    template_name = "sb_admin/widgets/multiwidget.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field,
            base_widget=SBAdminDateTimeWidget(),
        )


try:
    from cms.forms.widgets import PageSelectWidget

    class SBAdminPageSelectWidget(SBAdminBaseWidget, PageSelectWidget):
        template_name = "sb_admin/widgets/pageselectwidget.html"

        def __init__(self, form_field=None, attrs=None):
            self.form_field = form_field
            if attrs is not None:
                self.attrs = attrs.copy()
            else:
                self.attrs = {}
            self.choices = []
            super(PageSelectWidget, self).__init__(
                (SBAdminSelectWidget, SBAdminSelectWidget, SBAdminSelectWidget),
                attrs={"class": "input", **(self.attrs or {})},
            )

except ImportError:
    pass
