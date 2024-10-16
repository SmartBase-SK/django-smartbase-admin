import django.contrib.admin.helpers
from django.contrib.admin.utils import lookup_field, display_for_field
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import ManyToManyRel, ForeignObjectRel, OneToOneField
from django.template.defaultfilters import linebreaksbr
from django.template.loader import render_to_string
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from django_smartbase_admin.admin.site import sb_admin_site


class SBAdminReadonlyField(django.contrib.admin.helpers.AdminReadonlyField):
    readonly_template = "sb_admin/includes/readonly_field.html"
    readonly_boolean_template = "sb_admin/includes/readonly_boolean_field.html"

    def _boolean_field_content(self, value):
        return mark_safe(
            render_to_string(
                template_name=self.readonly_boolean_template,
                context={
                    "field_label": self.field.get("label"),
                    "field_name": self.field.get("name"),
                    "value": value,
                },
            ),
        )

    def contents(self, request=None):
        if self.model_admin.admin_site.name != sb_admin_site.name:
            return super().contents()

        field, obj, model_admin = (
            self.field["field"],
            self.form.instance,
            self.model_admin,
        )
        try:
            f, attr, value = lookup_field(field, obj, model_admin)
        except (AttributeError, ValueError, ObjectDoesNotExist):
            result_repr = self.empty_value_display
        else:
            if field in self.form.fields:
                widget = self.form[field].field.widget
                # This isn't elegant but suffices for contrib.auth's
                # ReadOnlyPasswordHashWidget.
                if getattr(widget, "read_only", False):
                    return widget.render(field, value)
            if f is None:
                if getattr(attr, "boolean", False):
                    return self._boolean_field_content(value)
                else:
                    if hasattr(value, "__html__"):
                        result_repr = value
                    else:
                        result_repr = linebreaksbr(value)
            else:
                base_field = self.form.fields.get(
                    field
                ) or model_admin.all_base_fields_form.base_fields.get(field)
                if isinstance(f.remote_field, ManyToManyRel) and value is not None:
                    # get label from widget if has base_field
                    if base_field:
                        result_repr = base_field.widget.get_label(
                            request, list(value.all())
                        )
                    else:
                        result_repr = ", ".join(map(str, value.all()))
                elif (
                    isinstance(f.remote_field, (ForeignObjectRel, OneToOneField))
                    and value is not None
                ):
                    # get label from widget if has base_field
                    if base_field:
                        result_repr = base_field.widget.get_label(
                            request, getattr(obj, field)
                        )
                    else:
                        result_repr = self.get_admin_url(f.remote_field, value)
                else:
                    if isinstance(f, models.BooleanField):
                        return self._boolean_field_content(value)
                    result_repr = display_for_field(value, f, self.empty_value_display)
                result_repr = linebreaksbr(result_repr)
        return render_to_string(
            template_name=self.readonly_template,
            context={
                "readonly_content": conditional_escape(result_repr),
                "field_label": self.field.get("label"),
            },
        )


django.contrib.admin.helpers.AdminReadonlyField = SBAdminReadonlyField
