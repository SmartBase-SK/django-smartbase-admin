import json
import os

from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row
from django.contrib.admin.utils import lookup_field
from django.core.exceptions import ObjectDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.template.defaultfilters import json_script
from django.templatetags.static import static
from django.utils.safestring import mark_safe
from django.utils.text import get_text_list
from django.utils.translation import gettext

from django_smartbase_admin.engine.const import ROW_CLASS_FIELD
from django_smartbase_admin.templatetags.base import InclusionSBAdminNode

register = template.Library()


class SBAdminJSONEncoder(DjangoJSONEncoder):
    def default(self, o):
        if callable(o):
            return o.__name__
        to_json_method = getattr(o, "to_json", None)
        if to_json_method:
            return to_json_method()
        return super().default(o)


@register.filter
def get_json(data):
    return json.dumps(data, cls=SBAdminJSONEncoder)


@register.filter
def get_json_script(value, element_id):
    to_json = getattr(value, "to_json", None)
    if to_json:
        return json_script(value.to_json(), element_id)
    return json_script(value, element_id)


@register.simple_tag
def get_item(dictionary, key):
    return dictionary.get(key, None) if dictionary else None


@register.tag(name="submit_row")
def submit_row_tag(parser, token):
    return InclusionSBAdminNode(
        parser, token, func=submit_row, template_name="submit_line.html"
    )


@register.simple_tag
def sb_admin_url(request_data, view_id, action, modifier=None):
    target_view = request_data.configuration.view_map.get(view_id)
    if target_view:
        return target_view.get_action_url(action=action, modifier=modifier)
    return ""


@register.simple_tag
def render_widget(widget, request):
    return widget.render(request)


@register.simple_tag(takes_context=True)
def sb_admin_render_form_field(context, form_field, label_as_placeholder=False):
    request = context["request"]
    from django_smartbase_admin.admin.admin_base import SBAdminFormFieldWidgetsMixin

    form_field.field = SBAdminFormFieldWidgetsMixin().assign_widget_to_form_field(
        form_field.field, request=request
    )
    if label_as_placeholder:
        form_field.field.widget.attrs["placeholder"] = form_field.field.label
        form_field.field.label = None
    return form_field.as_widget()


@register.simple_tag
def get_tabular_context(fieldsets, inlines, tabs):
    default_tabs = False
    any_error = False
    first_error_tab = True
    tabular_context = {}
    inlines_map = {inline.opts.__class__: inline for inline in inlines}
    fieldsets_map = {fieldset.name: fieldset for fieldset in fieldsets}
    if not tabs:
        tabs = {
            None: [*fieldsets_map.keys(), *inlines_map.keys()],
        }
        default_tabs = True
    for key, values in tabs.items():
        for value in values:
            has_error = False
            fieldset_value = fieldsets_map.get(value)
            inline_value = inlines_map.get(value)
            tabular_context[key] = tabular_context.get(
                key, {"content": [], "error": False, "classes": set()}
            )
            if fieldset_value:
                tabular_context[key]["content"].append(
                    {"type": "fieldset", "value": fieldset_value}
                )
                fieldset_fields = set()
                for field in fieldset_value.fields:
                    if isinstance(field, (list, tuple)):
                        fieldset_fields.update(set(field))
                    else:
                        fieldset_fields.add(field)
                error_present = bool(
                    set(fieldset_value.form.errors.keys()).intersection(fieldset_fields)
                )
                has_error = has_error or error_present
                tabular_context[key]["error"] = (
                    tabular_context[key]["error"] or error_present
                )
            if inline_value:
                tabular_context[key]["content"].append(
                    {"type": "inline", "value": inline_value}
                )
                error_present = inline_value.formset.total_error_count() != 0
                has_error = has_error or error_present
                tabular_context[key]["error"] = (
                    tabular_context[key]["error"] or error_present
                )
            if has_error:
                any_error = True
                tabular_context[key]["classes"].add("error")
                if first_error_tab:
                    tabular_context[key]["classes"].update(["active", "show"])
                    first_error_tab = False
    if not any_error:
        tabular_context[list(tabular_context.keys())[0]]["classes"].update(
            ["active", "show"]
        )
    return {
        "context": tabular_context,
        "default_tabs": default_tabs,
        "has_error": any_error,
    }


@register.filter
def to_class_name(value):
    return value.__class__.__name__


def get_change_message_legacy(log_entry):
    change_message = log_entry.change_message
    if change_message and change_message[0] == "[":
        try:
            change_message = json.loads(change_message)
        except json.JSONDecodeError:
            return change_message
        messages = []
        for sub_message in change_message:
            if "added" in sub_message:
                if sub_message["added"]:
                    sub_message["added"]["name"] = gettext(sub_message["added"]["name"])
                    messages.append(
                        gettext("Added {name} “{object}”.").format(
                            **sub_message["added"]
                        )
                    )
                else:
                    messages.append(gettext("Added."))

            elif "changed" in sub_message:
                sub_message["changed"]["fields"] = get_text_list(
                    [
                        gettext(field_name)
                        for field_name in sub_message["changed"]["fields"]
                    ],
                    gettext("and"),
                )
                if "name" in sub_message["changed"]:
                    sub_message["changed"]["name"] = gettext(
                        sub_message["changed"]["name"]
                    )
                    messages.append(
                        gettext("Changed {fields} for {name} “{object}”.").format(
                            **sub_message["changed"]
                        )
                    )
                else:
                    messages.append(
                        gettext("Changed {fields}.").format(**sub_message["changed"])
                    )

            elif "deleted" in sub_message:
                sub_message["deleted"]["name"] = gettext(sub_message["deleted"]["name"])
                messages.append(
                    gettext("Deleted {name} “{object}”.").format(
                        **sub_message["deleted"]
                    )
                )

        change_message = mark_safe(
            "<br/>".join(msg[0].upper() + msg[1:] for msg in messages)
        )
        return change_message or gettext("No fields changed.")
    else:
        return change_message


@register.simple_tag
def get_log_entry_message(log_entry):
    """
    If change_message is a JSON structure, interpret it as a change
    string, properly translated.
    """
    try:
        return get_change_message_legacy(log_entry)
    except Exception as e:
        return ""


@register.simple_tag
def call_method(obj, method_name, *args):
    method = getattr(obj, method_name, None)
    if method:
        return method(*args)
    return False


@register.simple_tag
def get_row_class(inline_admin_form):
    try:
        f, attr, value = lookup_field(
            ROW_CLASS_FIELD, inline_admin_form.original, inline_admin_form.model_admin
        )
    except (AttributeError, ValueError, ObjectDoesNotExist):
        return ""
    return value


@register.filter
def is_row_class_field(field):
    return isinstance(field, dict) and field["name"] == ROW_CLASS_FIELD


@register.simple_tag
def get_file_extension(file):
    if not file:
        return ""
    name, extension = os.path.splitext(file.name)
    return extension.lower().replace(".", "")


@register.simple_tag
def get_file_preview_image(
    file, file_extension=None, thumbnail_width=64, thumbnail_height=64
):
    file_extension = file_extension or get_file_extension(file)
    if file_extension in ["jpg", "png"]:
        from easy_thumbnails.files import get_thumbnailer

        thumbnailer = get_thumbnailer(file)
        thumb = thumbnailer.get_thumbnail(
            {
                "size": (thumbnail_width, thumbnail_height),
                "crop": True,
                "replace_alpha": "#fff",
            }
        )
        return thumb.url
    if file_extension == "svg":
        return file.url
    if file_extension == "pdf":
        # TODO change pdf file image
        return static("sb_admin/images/file_types/file-doc.svg")
    if file_extension in ["doc", "docx"]:
        return static("sb_admin/images/file_types/file-doc.svg")
    if file_extension in ["xls", "xlsx", "xlsm"]:
        return static("sb_admin/images/file_types/file-xlsx.svg")
    # TODO change default file image
    return static("sb_admin/images/file_types/file-doc.svg")
