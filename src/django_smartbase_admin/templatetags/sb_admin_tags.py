import json

from django import template
from django.contrib.admin.templatetags.admin_modify import submit_row
from django.core.serializers.json import DjangoJSONEncoder
from django.template.defaultfilters import json_script
from django.utils.translation import gettext

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
    has_error = False
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
            fieldset_value = fieldsets_map.get(value)
            inline_value = inlines_map.get(value)
            tabular_context[key] = tabular_context.get(
                key, {"content": [], "error": False, "classes": set()}
            )
            if fieldset_value:
                tabular_context[key]["content"].append(
                    {"type": "fieldset", "value": fieldset_value}
                )
                error_present = bool(fieldset_value.form.errors)
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
                tabular_context[key]["classes"].add("error")
                if first_error_tab:
                    tabular_context[key]["classes"].update(["active", "show"])
                    first_error_tab = False
    if not has_error:
        tabular_context[list(tabular_context.keys())[0]]["classes"].update(
            ["active", "show"]
        )
    return {
        "context": tabular_context,
        "default_tabs": default_tabs,
        "has_error": has_error,
    }


@register.filter
def to_class_name(value):
    return value.__class__.__name__


@register.simple_tag
def get_log_entry_message(log_entry):
    """
    If self.change_message is a JSON structure, interpret it as a change
    string, properly translated.
    """
    if log_entry.change_message and log_entry.change_message[0] == "[":
        try:
            change_message = json.loads(log_entry.change_message)
        except json.JSONDecodeError:
            return log_entry.change_message
        messages = []
        for sub_message in change_message:
            if "added" in sub_message:
                if sub_message["added"]:
                    obj_name, added_fields = sub_message["added"]
                    messages.append(
                        gettext("Added {obj_name} “{fields}”.\n").format(
                            obj_name=obj_name,
                            fields=added_fields,
                        )
                    )

                else:
                    messages.append(gettext("Added.\n"))

            elif "changed" in sub_message:
                try:
                    for fields in sub_message["changed"]:
                        if fields == "fields":
                            formatted_fields = (" and ").join(
                                sub_message["changed"][fields]
                            )
                            messages.append(
                                gettext("Changed {fields}.\n").format(
                                    fields=formatted_fields
                                )
                            )

                        else:
                            old_value, new_value = sub_message["changed"][fields]
                            old_value = fields + ": " + old_value
                            messages.append(
                                gettext(
                                    "Changed {old_value} for {new_value}.\n"
                                ).format(
                                    old_value=(
                                        old_value
                                        if len(old_value) - len(fields) <= 50
                                        else old_value[: 50 + len(fields)]
                                    ),
                                    new_value=(
                                        new_value
                                        if len(new_value) <= 50
                                        else new_value[:50]
                                    ),
                                    **sub_message["changed"],
                                )
                            )
                except Exception as e:
                    messages.append(str(sub_message["changed"]))
            elif "deleted" in sub_message:
                sub_message["deleted"]["name"] = gettext(sub_message["deleted"]["name"])
                messages.append(
                    gettext("Deleted {name} “{object}”.\n").format(
                        **sub_message["deleted"]
                    )
                )

        change_message = " ".join(msg[0].upper() + msg[1:] for msg in messages)
        return change_message or gettext("No fields changed.")
    else:
        return log_entry.change_message
