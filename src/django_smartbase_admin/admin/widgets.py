import json
import logging

from ckeditor.widgets import CKEditorWidget
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from django import forms
from django.conf import settings
from django.contrib.admin.widgets import (
    AdminURLFieldWidget,
    ForeignKeyRawIdWidget,
)
from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.core.exceptions import ValidationError
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

from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    SBAdminTreeWidgetMixin,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

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


class SBAdminMultipleChoiceWidget(SBAdminBaseWidget, forms.CheckboxSelectMultiple):
    template_name = "sb_admin/widgets/checkbox_select.html"
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
                    "altFormat": get_format("SHORT_DATE_FORMAT"),
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

    def __init__(self, form_field=None, attrs=None):
        super().__init__(
            form_field, attrs={"class": "input js-datetimepicker", **(attrs or {})}
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

    def __init__(self, form_field=None, *args, **kwargs):
        attrs = kwargs.pop("attrs", None)
        super().__init__(form_field, *args, **kwargs)
        self.attrs = {} if attrs is None else attrs.copy()

    def get_id(self):
        base_id = super().get_id()
        if self.form:
            base_id += f"_{self.form.__class__.__name__}"
        return base_id

    def init_widget_dynamic(self, form, form_field, field_name, view, request):
        super().init_widget_dynamic(form, form_field, field_name, view, request)
        if self.initialised:
            return
        self.initialised = True
        self.field_name = field_name
        self.view = view
        self.form = form
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
        if value:
            parsed_value = self.parse_value_from_input(threadsafe_request, value)
            if parsed_value:
                selected_options = []
                for item in self.get_queryset(threadsafe_request).filter(
                    **{f"{self.get_value_field()}{query_suffix}": parsed_value}
                ):
                    selected_options.append(
                        {
                            "value": self.get_value(threadsafe_request, item),
                            "label": self.get_label(threadsafe_request, item),
                        }
                    )

                related_model = self.model
                app_label = related_model._meta.app_label
                model_name = related_model._meta.model_name

                try:
                    change_url = reverse(
                        "sb_admin:{}_{}_change".format(
                            app_label, model_name
                        ), args=(parsed_value,)
                    )
                    add_url = reverse(
                        "sb_admin:{}_{}_add".format(app_label, model_name)
                    )

                    context["widget"]["attrs"]["related_edit_url"] = change_url
                    context["widget"]["attrs"]["related_add_url"] = add_url
                except:
                    pass
                context["widget"]["value"] = json.dumps(selected_options)
                context["widget"]["value_list"] = selected_options
        return context

    def is_multiselect(self):
        if self.multiselect is not None:
            return self.multiselect
        model_field = getattr(self.field, "model_field", None)
        return not (model_field and (model_field.one_to_one or model_field.many_to_one))

    def value_from_datadict(self, data, files, name):
        input_value = super().value_from_datadict(data, files, name)
        threadsafe_request = SBAdminThreadLocalService.get_request()
        parsed_value = self.parse_value_from_input(threadsafe_request, input_value)
        if parsed_value is None:
            return parsed_value
        return parsed_value if self.is_multiselect() else next(iter(parsed_value), None)

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
