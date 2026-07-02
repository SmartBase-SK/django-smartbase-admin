import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

from ckeditor.widgets import CKEditorWidget
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from django import forms
from django.conf import settings
from django.contrib.admin.widgets import (
    AdminURLFieldWidget,
    ForeignKeyRawIdWidget,
)
from django.contrib.auth.forms import ReadOnlyPasswordHashWidget
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.forms import RangeWidget
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db.models import ForeignKey, OneToOneField, Model
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.formats import get_format
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.utils.timezone import get_current_timezone_name
from django.utils.translation import gettext_lazy as _, get_language
from django.views.generic.base import ContextMixin
from filer.fields.file import AdminFileWidget as FilerAdminFileWidget
from filer.fields.image import AdminImageWidget
from filer.models import File

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
)
from django_smartbase_admin.engine.const import (
    ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR,
    Action,
)
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    SBAdminTreeWidgetMixin,
)
from django_smartbase_admin.services.request_cache import (
    RequestCacheKey,
    cache_on_request,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.templatetags.sb_admin_tags import (
    SBAdminJSONEncoder,
)
from django_smartbase_admin.utils import (
    convert_django_to_flatpickr_format,
    is_modal,
    sb_admin_filer_directory_listing_url_for_file,
)

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
            except Exception:
                pass
            widget_id = f"{modal_prefix}{opts.app_label}_{opts.model_name}_{context['widget']['attrs']['id']}"
            context["widget"]["attrs"]["id"] = widget_id
            # needed for BoundField.id_for_label to work correctly
            self.attrs["id"] = widget_id
        return context


class SBAdminInputAffixMixin:
    def __init__(
        self,
        *args,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
        prefix_button_attrs=None,
        suffix_button_attrs=None,
        media_js=(),
        **kwargs,
    ):
        self.validate_affix_config(
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
        )
        self.prefix = prefix
        self.suffix = suffix
        self.prefix_icon = prefix_icon
        self.suffix_icon = suffix_icon
        self.prefix_button_attrs = self.get_affix_button_attrs(
            (prefix_button_attrs or {}) if prefix_icon else None
        )
        self.suffix_button_attrs = self.get_affix_button_attrs(
            (suffix_button_attrs or {}) if suffix_icon else None
        )
        self.media_js = media_js
        super().__init__(*args, **kwargs)

    def validate_affix_config(
        self,
        *,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
    ):
        if prefix and prefix_icon:
            raise ImproperlyConfigured("Use either prefix or prefix_icon, not both.")
        if suffix and suffix_icon:
            raise ImproperlyConfigured("Use either suffix or suffix_icon, not both.")

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["prefix"] = self.prefix
        context["widget"]["suffix"] = self.suffix
        context["widget"]["prefix_icon"] = self.prefix_icon
        context["widget"]["suffix_icon"] = self.suffix_icon
        context["widget"]["prefix_button_attrs"] = (
            self.get_positioned_affix_button_attrs(
                self.prefix_button_attrs, "input-affix__prefix"
            )
        )
        context["widget"]["suffix_button_attrs"] = (
            self.get_positioned_affix_button_attrs(
                self.suffix_button_attrs, "input-affix__suffix"
            )
        )
        return context

    def get_affix_button_attrs(self, attrs):
        if attrs is None:
            return None
        attrs = dict(attrs)
        attrs.setdefault("type", "button")
        attrs["class"] = " ".join(
            filter(
                None,
                (
                    "input-affix__addon input-affix__button text-dark-900",
                    attrs.get("class", ""),
                ),
            )
        )
        return attrs

    def get_positioned_affix_button_attrs(self, attrs, position_class):
        if attrs is None:
            return None
        attrs = dict(attrs)
        attrs["class"] = " ".join(
            filter(None, (attrs.get("class", ""), position_class))
        )
        return attrs

    def get_attrs_with_affix_classes(
        self,
        attrs,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
    ):
        attrs = dict(attrs or {})
        classes = attrs.get("class", "")
        if prefix or prefix_icon:
            classes = f"{classes} rounded-l-none".strip()
        if suffix or suffix_icon:
            classes = f"{classes} rounded-r-none".strip()
        attrs["class"] = classes
        return attrs

    @property
    def media(self):
        media = super().media
        if self.media_js:
            media += forms.Media(js=self.media_js)
        return media


class SBAdminTextInputWidget(
    SBAdminInputAffixMixin, SBAdminBaseWidget, forms.TextInput
):
    template_name = "sb_admin/widgets/text.html"

    def __init__(
        self,
        form_field=None,
        attrs=None,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
        prefix_button_attrs=None,
        suffix_button_attrs=None,
        media_js=(),
    ):
        attrs = self.get_attrs_with_affix_classes(
            {"class": "input", **(attrs or {})},
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
        )
        super().__init__(
            form_field,
            attrs=attrs,
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
            prefix_button_attrs=prefix_button_attrs,
            suffix_button_attrs=suffix_button_attrs,
            media_js=media_js,
        )


class SBAdminCopyableTextInputWidget(SBAdminTextInputWidget):
    def __init__(
        self,
        form_field=None,
        attrs=None,
        prefix=None,
        suffix=None,
        *,
        copy_label="Copy",
        copied_label="Copied",
        copy_notification_label=None,
        copy_icon="Minus-the-top",
    ):
        copy_notification_label = copy_notification_label or copied_label
        super().__init__(
            form_field=form_field,
            attrs=attrs,
            prefix=prefix,
            suffix=suffix,
            suffix_icon=copy_icon,
            suffix_button_attrs={
                "title": copy_label,
                "aria-label": copy_label,
                "data-sbadmin-copy-button": True,
                "data-sbadmin-copy-label": copy_label,
                "data-sbadmin-copied-label": copied_label,
                "data-sbadmin-copy-notification-label": copy_notification_label,
            },
        )


class SBAdminTextTagsWidget(SBAdminBaseWidget, forms.TextInput):
    template_name = "sb_admin/widgets/text_tags.html"
    input_type = "text"

    def __init__(self, form_field=None, attrs=None, *, delimiter: str = ","):
        super().__init__(
            form_field,
            attrs={
                "class": "input js-sbadmin-text-tags",
                "data-choices-delimiter": delimiter,
                "autocomplete": "off",
                "dir": "ltr",
                **(attrs or {}),
            },
        )


class SBAdminPasswordInputWidget(SBAdminBaseWidget, forms.PasswordInput):
    template_name = "sb_admin/widgets/password.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminTextareaWidget(SBAdminBaseWidget, forms.Textarea):
    template_name = "sb_admin/widgets/textarea.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminEmailInputWidget(
    SBAdminInputAffixMixin, SBAdminBaseWidget, forms.EmailInput
):
    template_name = "sb_admin/widgets/email.html"

    def __init__(
        self,
        form_field=None,
        attrs=None,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
        prefix_button_attrs=None,
        suffix_button_attrs=None,
        media_js=(),
    ):
        attrs = self.get_attrs_with_affix_classes(
            {"class": "input", **(attrs or {})},
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
        )
        super().__init__(
            form_field,
            attrs=attrs,
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
            prefix_button_attrs=prefix_button_attrs,
            suffix_button_attrs=suffix_button_attrs,
            media_js=media_js,
        )


class SBAdminURLFieldWidget(SBAdminBaseWidget, AdminURLFieldWidget):
    template_name = "sb_admin/widgets/url.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "input", **(attrs or {})})


class SBAdminNumberWidget(SBAdminInputAffixMixin, SBAdminBaseWidget, forms.NumberInput):
    class_name = "input"
    template_name = "sb_admin/widgets/number.html"

    def __init__(
        self,
        form_field=None,
        attrs=None,
        prefix=None,
        suffix=None,
        prefix_icon=None,
        suffix_icon=None,
        prefix_button_attrs=None,
        suffix_button_attrs=None,
        media_js=(),
    ):
        attrs = self.get_attrs_with_affix_classes(
            {"class": self.class_name, **(attrs or {})},
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
        )
        super().__init__(
            form_field,
            attrs=attrs,
            prefix=prefix,
            suffix=suffix,
            prefix_icon=prefix_icon,
            suffix_icon=suffix_icon,
            prefix_button_attrs=prefix_button_attrs,
            suffix_button_attrs=suffix_button_attrs,
            media_js=media_js,
        )


class SBAdminCheckboxWidget(SBAdminBaseWidget, forms.CheckboxInput):
    template_name = "sb_admin/widgets/checkbox.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "checkbox", **(attrs or {})})


class SBAdminToggleWidget(SBAdminBaseWidget, forms.CheckboxInput):
    template_name = "sb_admin/widgets/toggle.html"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(form_field, attrs={"class": "toggle", **(attrs or {})})


class SBAdminCKEditorWidget(SBAdminBaseWidget, CKEditorWidget):
    dynamic_region_trigger_event = "SBAdminCKEditorChange"

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

    def __init__(
        self,
        form_field=None,
        attrs=None,
        choices=(),
        disable_empty_option=True,
    ):
        self.disable_empty_option = disable_empty_option
        super().__init__(
            form_field, attrs={"class": "input", **(attrs or {})}, choices=choices
        )

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if (
            self.disable_empty_option
            and (value is None or str(value) == "")
            and self.form_field is not None
            and getattr(self.form_field, "required", False)
        ):
            option_attrs = dict(option.get("attrs") or {})
            option_attrs["disabled"] = True
            option["attrs"] = option_attrs
        return option


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


class SBAdminChoiceSearchableWidget(SBAdminBaseWidget, forms.Select):
    """Single-choice dropdown with client-side search (Choices.js).

    Shares the autocomplete UI shell with ``SBAdminAutocompleteWidget`` but the
    options are rendered inline as ``<option>`` tags — no API fetch, no
    pagination. The native ``<select>`` submits as a single value, so a plain
    ``ChoiceField`` is enough on the backend.

    ``full_width`` is a class attribute so subclasses can flip the default
    without re-declaring ``__init__`` — useful when wiring this widget as the
    project-wide default via ``get_form_field_widget_class``.
    """

    template_name = "sb_admin/widgets/choice_search.html"
    full_width = False

    def __init__(self, form_field=None, attrs=None, choices=(), full_width=None):
        if full_width is not None:
            self.full_width = full_width
        super().__init__(
            form_field, attrs={"class": "input", **(attrs or {})}, choices=choices
        )

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["full_width"] = self.full_width
        return context


class SBAdminMultipleChoiceSearchableWidget(SBAdminBaseWidget, forms.SelectMultiple):
    """Multi-choice dropdown with client-side search (Choices.js).

    Same UI shell as ``SBAdminChoiceSearchableWidget`` but renders a
    ``<select multiple>`` and pairs with ``MultipleChoiceField``.
    """

    template_name = "sb_admin/widgets/choice_search.html"
    full_width = False

    def __init__(self, form_field=None, attrs=None, choices=(), full_width=None):
        if full_width is not None:
            self.full_width = full_width
        super().__init__(
            form_field, attrs={"class": "input", **(attrs or {})}, choices=choices
        )

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["full_width"] = self.full_width
        return context


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
                    "displayTimezoneLabel": get_current_timezone_name(),
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
                "data-sbadmin-datepicker": self.get_data(),
                "placeholder": get_datetime_placeholder()["time"],
                "autocomplete": "do-not-autofill",
                **(attrs or {}),
            },
        )

    def get_data(self):
        return json.dumps(
            {
                "flatpickrOptions": {
                    "displayTimezoneLabel": get_current_timezone_name(),
                },
            },
            cls=SBAdminJSONEncoder,
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
                    "displayTimezoneLabel": get_current_timezone_name(),
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


class SBAdminJsonEditorWidget(SBAdminBaseWidget, forms.TextInput):
    """JSON Schema editor backed by @json-editor/json-editor.

    Subclasses ``TextInput`` (not ``HiddenInput``) so SBAdmin's fieldset
    template doesn't hide the surrounding wrapper; the underlying input is
    hidden via the ``sbadmin-json-editor-input`` CSS class instead.
    """

    template_name = "sb_admin/widgets/json_editor.html"
    INPUT_HIDE_CLASS = "sbadmin-json-editor-input"
    jsoneditor_cdn_url = "https://cdn.jsdelivr.net/npm/@json-editor/json-editor@2.16.0/dist/jsoneditor.min.js"
    default_editor_options = {
        "theme": "sbadmin",
        "iconlib": "sbadmin",
        "disable_edit_json": True,
        "disable_properties": True,
        "disable_array_delete_all_rows": True,
        "disable_array_delete_last_row": True,
        "disable_array_reorder": False,
        "no_additional_properties": True,
        "prompt_before_delete": False,
    }

    def __init__(
        self,
        form_field=None,
        *,
        schema,
        attrs=None,
        editor_options=None,
        jsoneditor_cdn_url=None,
        add_to_top=False,
    ):
        self.schema = schema
        self.editor_options = {
            **self.default_editor_options,
            **(editor_options or {}),
        }
        self.add_to_top = add_to_top
        if jsoneditor_cdn_url is not None:
            self.jsoneditor_cdn_url = jsoneditor_cdn_url
        super().__init__(form_field, attrs=attrs)

    def format_value(self, value):
        return json.dumps(self._normalize_value(value), cls=SBAdminJSONEncoder)

    def get_context(self, name, value, attrs):
        normalized_value = self._normalize_value(value)
        attrs = dict(attrs or {})
        existing_class = attrs.get("class", "")
        if self.INPUT_HIDE_CLASS not in existing_class.split():
            attrs["class"] = (existing_class + " " + self.INPUT_HIDE_CLASS).strip()
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        widget_id = widget["attrs"].get("id") or f"id_{name}"
        # `form_name_root` namespaces generated input `name` attrs so two
        # editors on the same page can't collide on overlapping schema fields.
        editor_options = {
            **self.editor_options,
            "form_name_root": widget_id,
        }
        widget.update(
            {
                "json_editor_cdn_url": self.jsoneditor_cdn_url,
                "json_editor_editor_id": f"{widget_id}_editor",
                "json_editor_schema": self.schema,
                "json_editor_schema_id": f"{widget_id}_schema",
                "json_editor_value": normalized_value,
                "json_editor_value_id": f"{widget_id}_value",
                "json_editor_options": editor_options,
                "json_editor_options_id": f"{widget_id}_options",
                "json_editor_add_to_top": bool(self.add_to_top),
            }
        )
        return context

    def _empty_value(self):
        # Match the root schema type so non-array editors don't seed `[]`
        # into the hidden input (which then fails schema validation on a
        # plain submit without edits).
        schema_type = (self.schema or {}).get("type")
        if schema_type == "array":
            return []
        if schema_type == "object":
            return {}
        return None

    def _normalize_value(self, value):
        if value in (None, ""):
            return self._empty_value()
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return self._empty_value()
        return value

    def run_schema_validation(self, value):
        """Validate ``value`` against the widget's schema; raise ValidationError on failure."""
        if value in (None, "") or not self.schema:
            return
        import jsonschema

        validator = jsonschema.Draft7Validator(
            self._get_validation_schema(),
            format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
        )
        errors = sorted(
            validator.iter_errors(value), key=lambda e: list(e.absolute_path)
        )
        if not errors:
            return
        details = [
            f"{'.'.join(str(p) for p in err.absolute_path) or '(root)'}: {err.message}"
            for err in errors
        ]
        raise ValidationError(details)

    def _get_validation_schema(self):
        """Schema copy with ``additionalProperties: false`` injected (mirrors json-editor's ``no_additional_properties``)."""
        cached = getattr(self, "_validation_schema_cache", None)
        if cached is not None:
            return cached
        hardened = self._harden_schema_no_additional_properties(self.schema)
        self._validation_schema_cache = hardened
        return hardened

    @staticmethod
    def _harden_schema_no_additional_properties(schema):
        if not isinstance(schema, dict):
            return schema
        recurse = SBAdminJsonEditorWidget._harden_schema_no_additional_properties
        out = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                out[key] = {k: recurse(v) for k, v in value.items()}
            elif key == "items" and isinstance(value, dict):
                out[key] = recurse(value)
            else:
                out[key] = value
        if (
            out.get("type") == "object" or "properties" in out
        ) and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out


class SBAdminJsonEditorField(forms.JSONField):
    def __init__(
        self,
        *,
        schema,
        add_to_top=False,
        editor_options=None,
        widget=None,
        **kwargs,
    ):
        if widget is None:
            widget = SBAdminJsonEditorWidget(
                schema=schema,
                add_to_top=add_to_top,
                editor_options=editor_options,
            )
        kwargs["widget"] = widget
        super().__init__(**kwargs)

    def to_python(self, value):
        if value in self.empty_values:
            if hasattr(self.widget, "_empty_value"):
                return self.widget._empty_value()
            return None
        return super().to_python(value)

    def validate(self, value):
        super().validate(value)
        if hasattr(self.widget, "run_schema_validation"):
            self.widget.run_schema_validation(value)


class SBAdminAutocompleteWidget(
    SBAdminBaseWidget, AutocompleteFilterWidget, forms.Widget
):
    template_name = "sb_admin/widgets/autocomplete.html"
    dynamic_region_trigger_event = "SBAutocompleteChange"
    view = None
    form = None
    field_name = None
    initialised = None
    allow_add = None
    create_value_field = None
    default_create_data = None
    forward_to_create = None
    reload_on_save = None
    full_width = False
    REQUEST_CREATED_DATA_KEY = "autocomplete_created_data"

    def __init__(self, form_field=None, *args, **kwargs):
        attrs = kwargs.pop("attrs", None)
        self.reload_on_save = kwargs.pop("reload_on_save", False)
        self.allow_add = kwargs.pop("allow_add", None)
        self.create_value_field = kwargs.pop("create_value_field", None)
        self.forward_to_create = kwargs.pop("forward_to_create", [])
        self.full_width = kwargs.pop("full_width", self.full_width)
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
            action_id = getattr(self.form, "sbadmin_action_id", None)
            if action_id:
                separator = ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR
                base_id = f"{action_id}{separator}{base_id}"
        return base_id

    def get_autocomplete_url(self):
        request = SBAdminThreadLocalService.get_request()
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        return self.view.get_action_url(
            Action.AUTOCOMPLETE.value,
            modifier=self.get_id(),
            object_id=object_id,
        )

    def init_widget_dynamic(
        self, form, form_field, field_name, view, request, default_create_data=None
    ):
        super().init_widget_dynamic(form, form_field, field_name, view, request)
        self.bound_form = form
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
        request.request_data.register_autocomplete_view(self)

    def get_field_name(self):
        return self.field_name

    def get_selected_option_cache_key(self, request):
        formset = getattr(getattr(self, "bound_form", None), "_sbadmin_formset", None)
        formset_prefix = getattr(formset, "prefix", "") or ""
        return RequestCacheKey.autocomplete_selected_options(
            self.get_id(),
            formset_prefix,
            # Defensive: value_field changes how submitted values map back to rows.
            self.get_value_field(),
        )

    def get_selected_option_items_from_cache(self, request, parsed_value):
        formset = getattr(getattr(self, "bound_form", None), "_sbadmin_formset", None)
        if formset is None:
            return None

        def load_items_by_value():
            values = []
            value_set = set()
            for form in formset.forms:
                field = form.fields.get(self.field_name)
                if field is None or not isinstance(
                    field.widget, SBAdminAutocompleteWidget
                ):
                    continue
                raw_value = form[self.field_name].value()
                for value in field.widget.parse_value_list_from_input(
                    request, raw_value
                ):
                    value_key = str(value)
                    if value_key in value_set:
                        continue
                    value_set.add(value_key)
                    values.append(value)

            items_by_value = {}
            if values:
                for item in self.get_queryset(request).filter(
                    **{f"{self.get_value_field()}__in": values}
                ):
                    items_by_value[str(self.get_value(request, item))] = item
            return items_by_value

        items_by_value = cache_on_request(
            self.get_selected_option_cache_key(request),
            load_items_by_value,
            request=request,
        )
        parsed_values = (
            parsed_value if isinstance(parsed_value, list) else [parsed_value]
        )
        return [
            items_by_value[str(value)]
            for value in parsed_values
            if str(value) in items_by_value
        ]

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
        parsed_value = None
        selected_options = []
        has_bound_value = bool(value)
        if value:
            parsed_value = self.parse_value_from_input(threadsafe_request, value)
            is_create = self.parse_is_create_from_input(
                threadsafe_request,
                threadsafe_request.request_data.request_post.get(name),
            )
            if is_create:
                errors = getattr(self.form, "errors", {})
                if errors.get(self.field_name):
                    parsed_value = None
            if parsed_value:
                if self.is_multiselect() and not isinstance(parsed_value, list):
                    parsed_value = [parsed_value]
                elif not self.is_multiselect() and isinstance(parsed_value, list):
                    parsed_value = next(iter(parsed_value), None)

                try:
                    items = self.get_selected_option_items_from_cache(
                        threadsafe_request, parsed_value
                    )
                    if items is None:
                        items = self.get_queryset(threadsafe_request).filter(
                            **{f"{self.get_value_field()}{query_suffix}": parsed_value}
                        )
                    for item in items:
                        selected_options.append(
                            {
                                "value": self.get_value(threadsafe_request, item),
                                "label": self.get_label(threadsafe_request, item),
                            }
                        )
                except ValueError:
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

        elif self._should_preselect_parent_instance(threadsafe_request):
            parsed_value = threadsafe_request.GET.get(SBADMIN_PARENT_INSTANCE_PK_VAR)
            selected_options = [
                {
                    "value": parsed_value,
                    "label": threadsafe_request.GET.get(
                        SBADMIN_PARENT_INSTANCE_LABEL_VAR, ""
                    ),
                }
            ]

        if has_bound_value or selected_options:
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

    def _should_preselect_parent_instance(self, request):
        parent_field = request.GET.get(SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR)
        parent_pk = request.GET.get(SBADMIN_PARENT_INSTANCE_PK_VAR)
        return parent_field == self.input_id and bool(parent_pk)

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
                value_field = self.get_value_field()
                pk_field = self.model._meta.pk.name
                if value_field == pk_field:
                    context["widget"]["attrs"]["related_edit_url"] = (
                        related_model_admin.get_detail_url(parsed_value)
                    )
                else:
                    try:
                        related_row = (
                            related_model_admin.get_queryset(request)
                            .filter(**{value_field: parsed_value})
                            .values("pk")
                            .first()
                        )
                    except (ValueError, TypeError):
                        related_row = None
                    if related_row is not None:
                        context["widget"]["attrs"]["related_edit_url"] = (
                            related_model_admin.get_detail_url(related_row["pk"])
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
        """Resolve ``self.forward`` field names against the submitted form
        prefix and return ``{forward_field: raw_post_value}``. FK values are
        validated against the source field's (restricted) queryset before
        being returned, so any downstream consumer — ``filter_search_lambda``,
        ``Model.objects.create`` via ``get_forward_data_to_create``,
        ``validate`` — only ever sees PKs the user is allowed to reference.
        """
        forward_data = {}
        if not getattr(self, "forward", None):
            return forward_data

        post_data = getattr(request.request_data, "request_post", {})
        if not post_data:
            return forward_data

        form = getattr(self, "form", None)
        form_model = getattr(form, "model", None)

        for forward_field in self.forward:
            name_parts = name.split("-")
            if not (name_parts and name_parts[-1] == self.field_name):
                continue
            name_parts[-1] = forward_field
            forward_field_name = "-".join(name_parts)
            if forward_field_name not in post_data:
                continue

            raw_value = post_data.get(forward_field_name)
            self._validate_forwarded_value(
                request, form, form_model, forward_field, raw_value
            )
            forward_data[forward_field] = raw_value

        return forward_data

    def _validate_forwarded_value(
        self, request, form, form_model, field_name, raw_value
    ):
        if form is None or form_model is None:
            return
        try:
            model_field = form_model._meta.get_field(field_name)
        except FieldDoesNotExist:
            return
        if not isinstance(model_field, (ForeignKey, OneToOneField)):
            return

        parsed = self.parse_value_from_input(request, raw_value)
        if parsed is None:
            return
        if not isinstance(parsed, list):
            parsed = [parsed]
        pks = [p for p in parsed if p]
        if not pks:
            return

        source_field = form.fields.get(field_name)
        get_qs = getattr(getattr(source_field, "widget", None), "get_queryset", None)
        qs = (
            get_qs(request)
            if callable(get_qs)
            else getattr(source_field, "queryset", None)
        )
        # Fail closed: the form model declares this as a FK but we can't
        # locate a queryset to validate against, so we can't prove the PK
        # is reachable for the current user.
        if qs is None or qs.filter(pk__in=pks).count() != len(pks):
            raise ValidationError(
                self.form_field.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": raw_value},
            )

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
            self._check_create_permission(request, queryset.model)
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

    def _check_create_permission(self, request, model):
        # Route through the registered SBAdmin admin so SBAdminRoleConfiguration
        # .has_permission applies; fall back to Django model permission for
        # models without an SBAdmin admin registered.
        admin = sb_admin_site._registry.get(model)
        if admin is not None:
            if admin.has_add_permission(request):
                return
        else:
            user = getattr(request, "user", None)
            perm = f"{model._meta.app_label}.add_{model._meta.model_name}"
            if user is not None and user.has_perm(perm):
                return
        raise PermissionDenied

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
                related_url = sb_admin_filer_directory_listing_url_for_file(file_obj)
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


class SBAdminHiddenWidget(SBAdminBaseWidget, forms.HiddenInput):
    template_name = "sb_admin/widgets/hidden.html"


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
            "sb_admin/js/code.js",
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


@dataclass
class PermissionGroup:
    """Declarative definition for a group of permissions in
    :class:`SBAdminPermissionWidget`.

    Each group targets one model (or a set of explicit codenames).
    Use ``model`` (a Django model class) to look up permissions by
    content type, or ``codenames`` for an explicit list.  ``actions``
    controls which of the four standard Django actions are shown.
    """

    label: str
    """Display name for the group section."""

    model: Optional[type[Model]] = None
    """Django model class.  Permissions are resolved via content type."""

    codenames: Optional[list[str]] = None
    """Explicit list of permission codenames to include."""

    actions: tuple[str, ...] = ("view", "add", "change", "delete")
    """Which standard actions to show (``"view"``, ``"add"``,
    ``"change"``, ``"delete"``).  Ignored when ``codenames`` is set."""

    action_labels: dict[str, str] = field(default_factory=dict)
    """Custom labels for standard actions, e.g.
    ``{"view": _("See items"), "add": _("Create items")}``."""

    help_text: str = ""
    """Help text displayed below the group header."""


STANDARD_ACTIONS = ("view", "add", "change", "delete")


class SBAdminPermissionWidget(SBAdminBaseWidget, forms.Widget):
    """Collapsible, searchable permission tree widget for ``auth.Permission``.

    Two modes:

    **Default mode** — groups permissions by ``app_label`` / model.  Every
    Django permission is shown.  Use this when you want the full permission
    tree without any filtering.

    **Groups mode** — pass ``groups`` (a list of :class:`PermissionGroup`)
    to show only the permissions you define, with custom labels, help text,
    and control over which standard actions appear.
    """

    template_name = "sb_admin/widgets/permission_tree.html"
    sb_admin_widget = True

    def __init__(self, form_field=None, attrs=None, groups=None):
        super().__init__(
            form_field,
            attrs={"class": "permission-tree", **(attrs or {})},
        )
        self._groups = groups

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        selected = self._parse_value(value)

        if self._groups is not None:
            apps = self._build_groups_context(selected)
        else:
            apps = self._build_default_context(selected)

        context["widget"]["permission_apps"] = apps
        context["widget"]["selected_values"] = json.dumps(list(selected))
        return context

    def _build_default_context(self, selected):
        """Build context grouping permissions by app_label → model."""
        qs = Permission.objects.select_related("content_type").order_by(
            "content_type__app_label", "content_type__model", "codename"
        )
        apps = []
        current_app = None
        current_model = None
        app_idx = -1
        model_idx = -1

        for p in qs:
            ct = p.content_type
            ct_key = (ct.app_label, ct.model)

            if current_app != ct.app_label:
                app_idx += 1
                model_idx = -1
                apps.append(
                    {
                        "app_label": ct.app_label,
                        "app_verbose": ct.app_label.replace("_", " ").title(),
                        "help_text": "",
                        "models": [],
                    }
                )
                current_app = ct.app_label
                current_model = None

            if current_model != ct_key:
                model_idx += 1
                model_verbose = (
                    ct.name.replace("_", " ").title()
                    if ct.name
                    else ct.model.replace("_", " ").title()
                )
                apps[app_idx]["models"].append(
                    {
                        "model_name": ct.model,
                        "model_verbose": model_verbose,
                        "standard_perms": {},
                        "standard_perms_list": [],
                        "custom_perms": [],
                        "permissions": [],
                    }
                )
                current_model = ct_key

            is_standard = self._is_standard_codename(p.codename)
            perm_data = {
                "id": p.pk,
                "codename": p.codename,
                "name": p.name,
                "selected": p.pk in selected,
                "is_standard": is_standard,
            }
            apps[app_idx]["models"][model_idx]["permissions"].append(perm_data)

            if is_standard:
                action = self._standard_action(p.codename)
                apps[app_idx]["models"][model_idx]["standard_perms"][action] = perm_data
            else:
                apps[app_idx]["models"][model_idx]["custom_perms"].append(perm_data)

        for app in apps:
            for model in app["models"]:
                model["standard_perms_list"] = self._ordered_standard_perms(model)
        return apps

    def _build_groups_context(self, selected):
        """Build context from declared PermissionGroup definitions."""
        apps = []
        for idx, group in enumerate(self._groups):
            perms_qs = self._resolve_group_permissions(group)
            if not perms_qs.exists():
                continue

            ct = perms_qs.first().content_type
            model_verbose = (
                ct.name.replace("_", " ").title()
                if ct.name
                else ct.model.replace("_", " ").title()
            )

            model_data = {
                "model_name": ct.model,
                "model_verbose": model_verbose,
                "standard_perms": {},
                "standard_perms_list": [],
                "custom_perms": [],
                "permissions": [],
            }

            for p in perms_qs:
                is_standard = self._is_standard_codename(p.codename)
                if self._skip_standard_perm(group, p, is_standard):
                    continue
                name = self._resolve_group_perm_name(group, p, is_standard)
                perm_data = {
                    "id": p.pk,
                    "codename": p.codename,
                    "name": name,
                    "selected": p.pk in selected,
                    "is_standard": is_standard,
                }
                model_data["permissions"].append(perm_data)

                if is_standard:
                    action = self._standard_action(p.codename)
                    model_data["standard_perms"][action] = perm_data
                else:
                    model_data["custom_perms"].append(perm_data)

            model_data["standard_perms_list"] = self._ordered_standard_perms(model_data)

            apps.append(
                {
                    "app_label": group.label,
                    "app_verbose": group.label,
                    "help_text": group.help_text,
                    "models": [model_data],
                }
            )
        return apps

    # ------------------------------------------------------------------
    # Permission resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_group_permissions(group):
        """Return a queryset of Permission objects for one PermissionGroup."""
        if group.codenames is not None:
            qs = Permission.objects.filter(codename__in=group.codenames)
        elif group.model is not None:
            ct = ContentType.objects.get_for_model(group.model)
            qs = Permission.objects.filter(content_type=ct)
        else:
            return Permission.objects.none()
        return qs.select_related("content_type")

    @staticmethod
    def _resolve_group_perm_name(group, perm, is_standard):
        """Return the display name for a permission, checking
        ``group.action_labels`` for standard actions first."""
        if is_standard:
            action = perm.codename.rsplit("_", 1)[0]
            override = group.action_labels.get(action)
            if override is not None:
                return override
        return perm.name

    @staticmethod
    def _skip_standard_perm(group, perm, is_standard):
        """Return True if this standard permission should be skipped
        because its action is not in ``group.actions``."""
        if not is_standard:
            return False
        if group.codenames is not None:
            return False  # explicit list — show everything listed
        action = perm.codename.rsplit("_", 1)[0]
        return action not in group.actions

    @staticmethod
    def _ordered_standard_perms(model_data):
        return [
            model_data["standard_perms"].get(action)
            for action in STANDARD_ACTIONS
            if action in model_data["standard_perms"]
        ]

    # ------------------------------------------------------------------
    # Value I/O
    # ------------------------------------------------------------------

    def _get_allowed_permission_ids(self):
        """Return a ``frozenset`` of permission PKs that are valid
        given the current ``groups`` definition.

        When ``groups`` is ``None`` (default mode) all permissions are
        allowed, so this returns ``None`` (no restriction).
        """
        if self._groups is None:
            return None
        allowed = set()
        for group in self._groups:
            perms_qs = self._resolve_group_permissions(group)
            for p in perms_qs:
                if not self._skip_standard_perm(
                    group, p, self._is_standard_codename(p.codename)
                ):
                    allowed.add(p.pk)
        return frozenset(allowed)

    def value_from_datadict(self, data, files, name):
        raw = data.get(name)
        if not raw:
            return []
        try:
            values = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        allowed = self._get_allowed_permission_ids()
        if allowed is not None:
            return [v for v in values if v in allowed]
        return values

    @staticmethod
    def _is_standard_codename(codename):
        prefix = codename.rsplit("_", 1)[0] if "_" in codename else ""
        return prefix in ("view", "add", "change", "delete")

    @staticmethod
    def _standard_action(codename):
        return codename.rsplit("_", 1)[0]

    @staticmethod
    def _parse_value(value):
        if value is None:
            return set()
        if isinstance(value, (list, tuple)):
            return {int(v) for v in value if v is not None}
        if isinstance(value, str) and value:
            try:
                return set(json.loads(value))
            except (json.JSONDecodeError, TypeError):
                pass
        return set()
