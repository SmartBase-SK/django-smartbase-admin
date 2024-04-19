from django import forms
from django.contrib.admin.helpers import Fieldset
from django.template.loader import render_to_string


class JSONSerializableMixin(object):
    def to_json(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


def is_htmx_request(request_meta):
    return request_meta.get("HTTP_HX_REQUEST", False) != False


def querydict_to_dict(query_dict):
    data = {}
    for key in query_dict.keys():
        v = query_dict.getlist(key)
        if len(v) == 1:
            v = v[0]
        data[key] = v
    return data


def to_list(item):
    if not (isinstance(item, list) or isinstance(item, tuple)):
        item = [item]
    return item


def render_notifications(request):
    return render_to_string("sb_admin/includes/notifications.html", request=request)


class FormFieldsetMixin(forms.Form):
    def fieldsets(self):
        meta = getattr(self, "Meta", None)

        if not meta or not meta.fieldsets:
            yield Fieldset(form=self, fields=self.fields)
            return

        for name, data in meta.fieldsets:
            yield Fieldset(
                form=self,
                name=name,
                fields=data.get("fields", ()),
                classes=data.get("classes", ""),
            )
