from django.template.defaultfilters import date, time
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


def datetime_formatter(object_id, value):
    if value is None:
        return None
    value = timezone.localtime(value)
    return f"{date(value)} {time(value)}"


def datetime_formatter_with_format(date_format=None, time_format=None):
    def inner_formatter(object_id, value):
        value = timezone.localtime(value)
        return f"{date(value, date_format)} {time(value, time_format)}"

    return inner_formatter


def boolean_formatter(object_id, value):
    if value:
        return f'<span class="badge badge-simple badge-positive">{_("Yes")}</span>'
    return f'<span class="badge badge-simple badge-neutral">{_("No")}</span>'


def format_array(value_list, separator=""):
    result = ""
    if not value_list:
        return result
    for value in value_list:
        if not value:
            continue
        result += f'<span class="badge badge-simple badge-notice mr-4">{value}</span>{separator}'
    return result


def array_badge_formatter(object_id, value_list):
    return format_array(value_list)


def newline_separated_array_badge_formatter(object_id, value_list):
    return format_array(value_list, separator="<br>")
