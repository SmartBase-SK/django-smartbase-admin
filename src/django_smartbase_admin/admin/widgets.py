import json

from ckeditor.widgets import CKEditorWidget
from django import forms
from django.contrib.admin.widgets import (
    AdminURLFieldWidget,
)
from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.utils.translation import gettext_lazy as _
from django.views.generic.base import ContextMixin
from filer.fields.image import AdminImageWidget

from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget


class SBAdminBaseWidget(ContextMixin):
    sb_admin_widget = True

    def __init__(self, form_field=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.form_field = form_field

    def init_widget_dynamic(self, form_field):
        self.form_field = form_field

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["form_field"] = self.form_field
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
    template_name = "sb_admin/widgets/ckeditor.html"


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


class SBAdminNullBooleanSelectWidget(SBAdminBaseWidget, forms.NullBooleanSelect):
    template_name = "sb_admin/widgets/select.html"
    option_template_name = "sb_admin/widgets/select_option.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminDateWidget(SBAdminBaseWidget, forms.DateInput):
    template_name = "sb_admin/widgets/date.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field, attrs={"class": "input js-datepicker", **(attrs or {})}
        )


class SBAdminTimeWidget(SBAdminBaseWidget, forms.TimeInput):
    template_name = "sb_admin/widgets/time.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field, attrs={"class": "input js-timepicker", **(attrs or {})}
        )


class SBAdminDateTimeWidget(SBAdminBaseWidget, forms.DateTimeInput):
    template_name = "sb_admin/widgets/datetime.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field, attrs={"class": "input js-datetimepicker", **(attrs or {})}
        )


class SBAdminSplitDateTimeWidget(forms.SplitDateTimeWidget):
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


class SBAdminAutocompleteWidget(
    SBAdminBaseWidget, AutocompleteFilterWidget, forms.Widget
):
    template_name = "sb_admin/widgets/autocomplete.html"
    view = None
    field_name = None
    threadsafe_request = None
    initialised = None

    def __init__(self, form_field=None, *args, **kwargs):
        super().__init__(form_field, *args, **kwargs)

    def init_widget_dynamic(self, form_field, field_name, view, request):
        super().init_widget_dynamic(form_field)
        if self.initialised:
            return
        self.initialised = True
        self.field_name = field_name
        self.view = view
        self.threadsafe_request = request
        self.init_autocomplete_widget_static(
            self.field_name,
            self.model,
            self.threadsafe_request.request_data.configuration,
        )

    def get_field_name(self):
        return self.field_name

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        self.input_id = f'id_{context["widget"]["name"]}'
        context["widget"]["type"] = "hidden"
        context["widget"]["attrs"]["id"] = self.input_id
        context["widget"]["attrs"]["class"] = "js-autocomplete-detail"
        context["widget"]["attrs"]["data-empty-label"] = getattr(
            self.form_field, "empty_label", None
        )
        query_suffix = "__in"
        if not self.is_multiselect():
            query_suffix = ""
            self.multiselect = False
        if value:
            parsed_value = self.parse_value_from_input(self.threadsafe_request, value)
            if parsed_value:
                selected_options = []
                for item in self.get_queryset(self.threadsafe_request).filter(
                    **{f"{self.get_value_field()}{query_suffix}": parsed_value}
                ):
                    selected_options.append(
                        {
                            "value": self.get_value(self.threadsafe_request, item),
                            "label": self.get_label(self.threadsafe_request, item),
                        }
                    )
                context["widget"]["value"] = json.dumps(selected_options)
        return context

    def is_multiselect(self):
        if self.multiselect is not None:
            return self.multiselect
        model_field = getattr(self.field, "model_field", None)
        return not (model_field and (model_field.one_to_one or model_field.many_to_one))

    def value_from_datadict(self, data, files, name):
        input_value = super().value_from_datadict(data, files, name)
        parsed_value = self.parse_value_from_input(self.threadsafe_request, input_value)
        if parsed_value is None:
            return parsed_value
        return parsed_value if self.is_multiselect() else next(iter(parsed_value), None)

    @classmethod
    def apply_to_model_field(cls, model_field):
        return None


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


class SBAdminReadOnlyPasswordHashWidget(SBAdminBaseWidget, ReadOnlyPasswordHashWidget):
    template_name = "sb_admin/widgets/read_only_password_hash.html"


class SBAdminHiddenWidget(SBAdminBaseWidget, forms.Widget):
    template_name = "sb_admin/widgets/hidden.html"
    input_type = "hidden"
