import logging
from collections.abc import Iterable

from django import forms
from django.conf import settings
from django.contrib.admin.helpers import Fieldset
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


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
    if item is None:
        return []
    if not (isinstance(item, list) or isinstance(item, tuple)):
        item = [item]
    return item


def render_notifications(request):
    return render_to_string("sb_admin/includes/notifications.html", request=request)


def is_modal(request):
    from django_smartbase_admin.engine.admin_base_view import SBADMIN_IS_MODAL_VAR

    return request and (
        SBADMIN_IS_MODAL_VAR in request.GET or SBADMIN_IS_MODAL_VAR in request.POST
    )


class FormFieldsetMixin(forms.Form):
    def get_fieldsets(self) -> Iterable[tuple[str | None, dict]]:
        meta = getattr(self, "Meta", None)
        return getattr(meta, "fieldsets", tuple())

    def fieldsets(self) -> Iterable[Fieldset]:
        if not (fieldsets := self.get_fieldsets()):
            logger.warning(
                "No fieldsets defined for form %s. Using form fields as fallback.",
                self.__class__.__name__,
            )
            yield Fieldset(form=self, fields=self.fields)
            return

        for name, data in fieldsets:
            yield Fieldset(
                form=self,
                name=name,
                fields=data.get("fields", ()),
                classes=data.get("classes", ""),
            )


def _pluck_classes(modules, classnames):
    """
    Gets a list of class names and a list of modules to pick from.
    For each class name, will return the class from the first module that has a
    matching class.
    """
    klasses = []
    for classname in classnames:
        klass = None
        for module in modules:
            if hasattr(module, classname):
                klass = getattr(module, classname)
                break
        if not klass:
            packages = [m.__name__ for m in modules if m is not None]
            raise Exception(
                "No class '%s' found in %s" % (classname, ", ".join(packages))
            )
        klasses.append(klass)
    return klasses


def import_with_injection(from_import, import_name):
    original_module = __import__(from_import, fromlist=[import_name])
    full_path = f"{from_import}.{import_name}"
    overridden_module = None

    SB_ADMIN_DEPENDENCY_INJECTION = getattr(
        settings, "SB_ADMIN_DEPENDENCY_INJECTION", {}
    )
    if full_path in SB_ADMIN_DEPENDENCY_INJECTION:
        overridden_module = __import__(
            SB_ADMIN_DEPENDENCY_INJECTION[full_path][0],
            fromlist=[SB_ADMIN_DEPENDENCY_INJECTION[full_path][1]],
        )
    if overridden_module:
        return _pluck_classes([overridden_module, original_module], [import_name])[0]
    else:
        return _pluck_classes([original_module], [import_name])[0]
