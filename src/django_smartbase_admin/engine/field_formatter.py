from enum import Enum

from django.template.defaultfilters import date, time
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class BadgeType(Enum):
    SUCCESS = "positive"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "negative"


def datetime_formatter(object_id, value):
    if value is None:
        return None
    value = timezone.localtime(value)
    return f"{date(value)} {time(value)}"


def datetime_formatter_with_format(date_format=None, time_format=None):
    def inner_formatter(object_id, value):
        if value is None:
            return None
        value = timezone.localtime(value)
        return_value = ""
        if date_format:
            return_value += date(value, date_format)
        if time_format:
            if return_value:
                return_value += " "
            return_value += time(value, time_format)
        return return_value

    return inner_formatter


def boolean_formatter(object_id, value):
    if value:
        return mark_safe(
            f'<span class="badge badge-simple badge-positive">{_("Yes")}</span>'
        )
    return mark_safe(f'<span class="badge badge-simple badge-neutral">{_("No")}</span>')


def format_array(value_list, separator="", badge_type: BadgeType = BadgeType.NOTICE):
    result = ""
    if not value_list:
        return result
    for value in value_list:
        if not value:
            continue
        result += f'<span class="badge badge-simple badge-{badge_type.value} mr-4">{value}</span>{separator}'
    return mark_safe(result)


def array_badge_formatter(object_id, value_list):
    return format_array(value_list)


def newline_separated_array_badge_formatter(object_id, value_list):
    return format_array(value_list, separator="<br>")


def rich_text_formatter(object_id, value):
    return mark_safe(
        f'<div style="max-width: 500px; white-space: normal;">{value}</div>'
    )


def link_formatter(object_id, value):
    return mark_safe(f'<a href="{value}">{value}</a>')
