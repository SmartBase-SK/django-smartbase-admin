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


# Mapping of Django date format tokens to flatpickr format tokens
# Only tokens that differ between Django and flatpickr are included
# Reference: https://docs.djangoproject.com/en/stable/ref/templates/builtins/#date
# Reference: https://flatpickr.js.org/formatting/
DJANGO_TO_FLATPICKR_TOKEN_MAP = {
    # Time tokens
    "A": "K",  # Django AM/PM -> flatpickr AM/PM
    "a": "K",  # Django am/pm (lowercase) -> flatpickr K (no lowercase option)
    "G": "H",  # Django 24-hour no padding -> flatpickr H (closest, has padding)
    "g": "h",  # Django 12-hour no padding -> flatpickr h
    "s": "S",  # Django seconds -> flatpickr S (case difference)
    # Month tokens
    "N": "M",  # Django month abbreviation (AP style) -> flatpickr short month
    "b": "M",  # Django lowercase month abbreviation -> flatpickr short month
    "E": "F",  # Django locale month name -> flatpickr full month name
    # Day tokens
    "j": "j",  # Same: day without leading zero
    "S": "",  # Django ordinal suffix (st, nd, rd, th) -> no flatpickr equivalent
    "w": "w",  # Same: day of week (0-6)
    # Week/Year tokens
    "o": "Y",  # Django ISO-8601 week-numbering year -> flatpickr year (approximate)
    "W": "W",  # Same: ISO-8601 week number
    # Timezone tokens - flatpickr doesn't support timezones
    "e": "",  # Django timezone name -> not supported
    "O": "",  # Django UTC offset (+0200) -> not supported
    "T": "",  # Django timezone abbreviation -> not supported
    "Z": "",  # Django timezone offset in seconds -> not supported
    # The 'P' token (12-hour format with minutes and a.m./p.m.) is complex
    # We handle it separately in the conversion function
}

# Tokens that are the same in both Django and flatpickr (for reference):
# d - day with leading zero (01-31)
# D - short day name (Mon, Tue)
# l - full day name (Monday, Tuesday)
# m - month with leading zero (01-12)
# n - month without leading zero (1-12)
# M - short month name (Jan, Feb)
# F - full month name (January, February)
# y - 2-digit year (99)
# Y - 4-digit year (1999)
# H - 24-hour with leading zero (00-23)
# h - 12-hour with leading zero in flatpickr (but different in Django!)
# i - minutes with leading zero (00-59)


def convert_django_to_flatpickr_format(django_format):
    """
    Convert a Django date/datetime format string to flatpickr format string.

    Django and flatpickr use similar but not identical format tokens.
    This function handles the conversion for tokens that differ.

    Args:
        django_format: A Django date format string (e.g., "d.m.Y H:i")

    Returns:
        A flatpickr-compatible format string

    Example:
        >>> convert_django_to_flatpickr_format("d.m.Y H:i")
        'd.m.Y H:i'
        >>> convert_django_to_flatpickr_format("m/d/Y g:i A")
        'm/d/Y h:i K'
    """
    if not django_format:
        return django_format

    result = []
    i = 0
    length = len(django_format)

    while i < length:
        char = django_format[i]

        # Handle Django's 'P' token specially (12-hour time with a.m./p.m.)
        # Convert to flatpickr equivalent: h:i K
        if char == "P":
            result.append("h:i K")
            i += 1
            continue

        # Check if this character is a Django token that needs conversion
        if char in DJANGO_TO_FLATPICKR_TOKEN_MAP:
            result.append(DJANGO_TO_FLATPICKR_TOKEN_MAP[char])
        else:
            # Keep the character as-is (either same in both or a literal)
            result.append(char)

        i += 1

    return "".join(result)
