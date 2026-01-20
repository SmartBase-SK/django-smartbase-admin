from enum import Enum

from django.template.defaultfilters import date, time
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


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
        return format_html(
            '<span class="badge badge-simple badge-positive">{}</span>', _("Yes")
        )
    return format_html(
        '<span class="badge badge-simple badge-neutral">{}</span>', _("No")
    )


def format_array(value_list, separator="", badge_type: BadgeType = BadgeType.NOTICE):
    if not value_list:
        return ""

    # `separator` is intended to be an internal constant (e.g. "" or "<br>").
    # We mark it safe so HTML separators render as HTML rather than being escaped.
    sep = mark_safe(separator) if separator else ""
    return format_html_join(
        sep,
        '<span class="badge badge-simple badge-{} mr-4">{}</span>',
        ((badge_type.value, value) for value in value_list if value),
    )


def array_badge_formatter(object_id, value_list):
    return format_array(value_list)


def newline_separated_array_badge_formatter(object_id, value_list):
    return format_html("<div>{}</div>", format_array(value_list, separator="<br>"))


def rich_text_formatter(object_id, value):
    # Intentionally renders HTML (e.g. from a rich text editor field).
    return format_html(
        '<div style="max-width: 500px; white-space: normal;">{}</div>',
        mark_safe(value) if value else "",
    )


def link_formatter(object_id, value):
    if not value:
        return ""
    return format_html('<a href="{0}">{0}</a>', value)
