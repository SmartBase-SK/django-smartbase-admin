from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.contrib.postgres.fields import ArrayField
from django.db.models import Field, Q, fields, FilteredRelation, Count
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from django_smartbase_admin.actions.advanced_filters import (
    AllOperators,
    STRING_ATTRIBUTES,
    NUMBER_ATTRIBUTES,
    DATE_ATTRIBUTES,
)
from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import (
    AUTOCOMPLETE_SEARCH_NAME,
    AUTOCOMPLETE_PAGE_SIZE,
    Action,
    AUTOCOMPLETE_PAGE_NUM,
    AUTOCOMPLETE_FORWARD_NAME,
    SELECT_ALL_KEYWORD,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder
from django_smartbase_admin.utils import JSONSerializableMixin
from typing_extensions import Self

if TYPE_CHECKING:
    from django_smartbase_admin.engine.field import SBAdminField


class AutocompleteParseMixin:
    def parse_value_from_input(self, request, input_value):
        try:
            input_value = json.loads(input_value)
        except:
            pass
        if isinstance(input_value, list):
            value = []
            for data in input_value:
                if type(data) is dict:
                    value.append(data["value"])
                else:
                    value.append(data)
        else:
            value = input_value
        return value

    def parse_value_list_from_input(self, request, input_value):
        parsed_value = self.parse_value_from_input(request, input_value)
        if parsed_value in forms.Field.empty_values:
            return []
        if not isinstance(parsed_value, list):
            parsed_value = [parsed_value]
        return [
            value for value in parsed_value if value not in forms.Field.empty_values
        ]

    def parse_is_create_from_input(self, request, input_value):
        try:
            input_value = json.loads(input_value)
        except:
            pass
        if isinstance(input_value, list):
            value = []
            for data in input_value:
                if type(data) is dict:
                    value.append(data.get("create", False))
                else:
                    value.append(False)
        else:
            value = False
        return value


class SBAdminFilterWidget(JSONSerializableMixin):
    template_name = None
    field = None
    model_field = None
    view = None
    view_id = None
    input_id = None
    input_name = None
    default_value = None
    default_label = None
    filter_query_lambda = None
    exclude_null_operators = False
    # If True, the filter dropdown closes after the filter value changes (frontend behavior).
    # Useful for single-step filters; set to False for widgets where users typically make multiple
    # changes before closing the dropdown.
    close_dropdown_on_change = False
    allow_clear = True

    def __init__(
        self,
        template_name=None,
        default_value=None,
        default_label=None,
        filter_query_lambda=None,
        exclude_null_operators=None,
        close_dropdown_on_change=None,
        allow_clear=None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.template_name = self.template_name or template_name
        self.default_value = self.default_value or default_value
        self.default_label = self.default_label or default_label
        self.filter_query_lambda = filter_query_lambda or self.filter_query_lambda
        self.exclude_null_operators = (
            exclude_null_operators or self.exclude_null_operators
        )
        if close_dropdown_on_change is not None:
            self.close_dropdown_on_change = close_dropdown_on_change
        if allow_clear is not None:
            self.allow_clear = allow_clear

    def init_filter_widget_static(self, field, view, configuration):
        self.field = field
        self.model_field = field.model_field
        self.view = view
        self.view_id = view.get_id()
        self.input_id = f"{self.view_id}-{self.field.filter_field}"
        self.input_name = self.field.filter_field
        self.after_init()

    def after_init(self):
        pass

    def parse_value_from_input(self, request, filter_value):
        return filter_value

    def validate_value(self, value) -> None:
        if not isinstance(value, str):
            raise ValueError(
                f"{type(self).__name__} expects a string, got {type(value).__name__}: {value!r}"
            )

    def get_filter_query_for_value(self, request, filter_value):
        parsed_value = self.parse_value_from_input(request, filter_value)
        if self.filter_query_lambda:
            return self.filter_query_lambda(request, parsed_value)
        return self.get_base_filter_query_for_parsed_value(request, parsed_value)

    def get_base_filter_query_for_parsed_value(self, request, parsed_value):
        return Q(**{f"{self.field.filter_field}__icontains": parsed_value})

    def get_advanced_filter_query_for_parsed_value(
        self, request, parsed_value, original_query, rule
    ):
        return original_query

    def to_json(self):
        return {
            "input_id": self.input_id,
        }

    def get_default_value(self):
        return self.default_value

    def get_default_label(self):
        return self.default_label or self.get_default_value()

    @classmethod
    def is_used_for_model_field_type(cls, model_field: Field) -> bool:
        return False

    @classmethod
    def apply_to_field(cls, field: SBAdminField) -> Self | None:
        return cls.apply_to_model_field(field.model_field)

    @classmethod
    def apply_to_model_field(cls, model_field: Field) -> Self | None:
        if cls.is_used_for_model_field_type(model_field):
            return cls()
        return None

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["filter_widget"] = self
        return context

    def get_advanced_filter_operators(self):
        return [
            AllOperators.EQUAL,
            AllOperators.NOT_EQUAL,
            AllOperators.IS_NULL,
            AllOperators.IS_NOT_NULL,
        ]


class StringFilterWidget(SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/string_field.html"
    close_dropdown_on_change = True

    def get_advanced_filter_operators(self):
        return STRING_ATTRIBUTES

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return (
            isinstance(model_field, fields.CharField)
            or isinstance(model_field, fields.TextField)
            or isinstance(model_field, fields.IntegerField)
            or isinstance(model_field, fields.AutoField)
        )


class BooleanFilterWidget(SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/boolean_field.html"
    choices = None
    close_dropdown_on_change = True

    def __init__(
        self,
        template_name=None,
        default_value=None,
        default_label=None,
        filter_query_lambda=None,
        exclude_null_operators=None,
        close_dropdown_on_change=None,
        **kwargs,
    ) -> None:
        super().__init__(
            template_name,
            default_value,
            default_label,
            filter_query_lambda,
            exclude_null_operators,
            close_dropdown_on_change,
            **kwargs,
        )
        self.choices = ((True, _("Yes")), (False, _("No")))

    def parse_value_from_input(self, request, filter_value):
        input_value = super().parse_value_from_input(request, filter_value)
        try:
            input_value = json.loads(input_value)
        except:
            pass

        if input_value is None:
            return None
        return input_value

    def validate_value(self, value) -> None:
        if value is None or isinstance(value, bool):
            return
        raise ValueError(
            f"BooleanFilterWidget expects a bool, got {type(value).__name__}: {value!r}"
        )

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return isinstance(model_field, fields.BooleanField)

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        return Q(**{f"{self.field.filter_field}": filter_value})


class ChoiceFilterWidget(SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/choice_field.html"
    choices = None
    close_dropdown_on_change = True

    def __init__(
        self,
        choices,
        template_name=None,
        default_value=None,
        default_label=None,
        **kwargs,
    ) -> None:
        super().__init__(
            template_name=template_name,
            default_value=default_value,
            default_label=default_label,
            **kwargs,
        )
        self.choices = self.choices or choices

    @property
    def grouped_choices(self):
        """Normalise ``choices`` into ``[(group_label_or_None, [(value, label), ...])]``.

        Accepts flat ``[(value, label), ...]`` and Django-style grouped
        ``[(group_label, [(value, label), ...]), ...]``. Flat input becomes a
        single ``None``-labelled group so templates iterate uniformly and skip
        the header when ``group_label`` is falsy. Mirrors the detection
        ``ChoiceWidget.optgroups`` uses internally.
        """
        if not self.choices:
            return []
        items = list(self.choices)
        first = items[0]
        is_grouped = (
            isinstance(first, (list, tuple))
            and len(first) == 2
            and isinstance(first[1], (list, tuple))
        )
        if is_grouped:
            return [(group_label, list(options)) for group_label, options in items]
        return [(None, items)]

    @property
    def flat_choices(self):
        """Flat ``[(value, label), ...]`` view of ``choices`` — same list for
        both flat and grouped input. Use this for label lookup."""
        flat = []
        for _, options in self.grouped_choices:
            flat.extend(options)
        return flat

    def get_default_label(self):
        if self.default_label:
            return self.default_label
        else:
            default_value = self.get_default_value()
            found_label = [
                label for value, label in self.flat_choices if value == default_value
            ]
            return found_label[0] if found_label else default_value

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        if isinstance(self.model_field, ArrayField):
            return Q(**{f"{self.field.filter_field}__contains": [filter_value]})
        return Q(**{self.field.filter_field: filter_value})


class RadioChoiceFilterWidget(ChoiceFilterWidget):
    template_name = "sb_admin/filter_widgets/radio_choice_field.html"
    close_dropdown_on_change = True


class MultipleChoiceFilterWidget(AutocompleteParseMixin, ChoiceFilterWidget):
    template_name = "sb_admin/filter_widgets/multiple_choice_field.html"
    enable_select_all = False
    select_all_keyword = None
    select_all_label = None
    close_dropdown_on_change = False

    def __init__(
        self,
        choices,
        template_name=None,
        default_value=None,
        default_label=None,
        enable_select_all=False,
        select_all_keyword=SELECT_ALL_KEYWORD,
        select_all_label=_("All"),
        **kwargs,
    ) -> None:
        super().__init__(
            choices=choices,
            template_name=template_name,
            default_value=default_value,
            default_label=default_label,
            **kwargs,
        )
        self.enable_select_all = enable_select_all
        self.select_all_keyword = select_all_keyword
        self.select_all_label = select_all_label

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        if isinstance(self.model_field, ArrayField):
            q_objects = Q()
            for value in filter_value:
                q_objects |= Q(**{f"{self.field.filter_field}__contains": [value]})
            return q_objects
        return Q(**{f"{self.field.filter_field}__in": filter_value})

    def validate_value(self, value) -> None:
        if not isinstance(value, list):
            raise ValueError(
                f"MultipleChoiceFilterWidget expects a list of choice values, got {type(value).__name__}: {value!r}"
            )

    def get_advanced_filter_operators(self):
        return [
            AllOperators.IN,
            AllOperators.NOT_IN,
            AllOperators.IS_NULL,
            AllOperators.IS_NOT_NULL,
        ]

    @classmethod
    def is_used_for_model_field_type(cls, model_field: Field) -> bool:
        return bool(getattr(model_field, "flatchoices", None))

    @classmethod
    def apply_to_model_field(cls, model_field: Field) -> Self | None:
        if cls.is_used_for_model_field_type(model_field):
            return cls(choices=model_field.choices)
        return None


class PrimaryKeyFilterWidget(SBAdminFilterWidget):
    """Exact-match / ``IN`` filter on a primary key.

    Accepts a single pk or a list of pks and filters
    ``<filter_field>__in=[...]``. Attached to the synthetic primary-key
    column the list view exposes when the admin hasn't declared one, so a
    row can be re-fetched by the ``id`` it already shows — in the browser
    (a text box: one id, or several comma-separated) and over MCP (a pk or
    a list of pks). Not auto-detected for any model field type; only used
    when set explicitly.
    """

    # A pk is typed, not picked — reuse the plain text-input template.
    template_name = "sb_admin/filter_widgets/string_field.html"
    close_dropdown_on_change = True

    _SEPARATORS = re.compile(r"[\s,;]+")

    def parse_value_from_input(self, request, filter_value):
        """Flat list of pks. Accepts a native scalar/list (MCP) or a string of
        pks separated by commas, whitespace, or semicolons (the UI text box).
        Values are coerced through the pk field; ones that can't be this pk
        (e.g. ``"abc"`` for an int pk) are dropped, not handed to the ORM."""
        value = filter_value
        if isinstance(value, str):
            value = [part for part in self._SEPARATORS.split(value.strip()) if part]
        if not isinstance(value, list):
            value = [value]
        parsed = []
        for item in value:
            if item in forms.Field.empty_values:
                continue
            if self.model_field is not None:
                try:
                    item = self.model_field.get_prep_value(item)
                except (ValueError, TypeError, ValidationError):
                    continue
            parsed.append(item)
        return parsed

    def get_base_filter_query_for_parsed_value(self, request, parsed_value):
        if not parsed_value:
            # Truly-empty values are dropped before the widget runs, so an
            # empty list here is non-empty input that coerced to nothing —
            # invalid. Fail closed so an active filter can't silently widen to
            # the whole table (which would also widen bulk actions / exports).
            return Q(pk__in=[])
        return Q(**{f"{self.field.filter_field}__in": parsed_value})

    def validate_value(self, value) -> None:
        items = value if isinstance(value, list) else [value]
        for item in items:
            # ``bool`` is an ``int`` subclass but never a valid pk here.
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ValueError(
                    "PrimaryKeyFilterWidget expects a primary key or a list of "
                    "primary keys (int or str), got "
                    f"{type(item).__name__}: {item!r}"
                )
            # Reject up front so MCP gets a clear error, not an ORM failure
            # mid-query.
            if self.model_field is not None:
                try:
                    self.model_field.get_prep_value(item)
                except (ValueError, TypeError, ValidationError):
                    raise ValueError(
                        f"PrimaryKeyFilterWidget got {item!r}, not a valid "
                        f"{self.model_field.get_internal_type()} id"
                    )

    def get_advanced_filter_operators(self):
        return [
            AllOperators.IN,
            AllOperators.NOT_IN,
            AllOperators.IS_NULL,
            AllOperators.IS_NOT_NULL,
        ]


class NumberRangeFilterWidget(AutocompleteParseMixin, SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/number_range_field.html"

    def parse_value_from_input(self, request, filter_value):
        filter_value = super().parse_value_from_input(request, filter_value)
        try:
            from_value = float(filter_value.get("from", {}).get("value", None))
        except (ValueError, TypeError):
            from_value = None
        try:
            to_value = float(filter_value.get("to", {}).get("value", None))
        except (ValueError, TypeError):
            to_value = None

        return [from_value, to_value]

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        result = Q()
        if filter_value[0] is not None:
            result &= Q(**{f"{self.field.filter_field}__gte": filter_value[0]})
        if filter_value[1] is not None:
            result &= Q(**{f"{self.field.filter_field}__lte": filter_value[1]})
        return result

    def validate_value(self, value) -> None:
        # Same shape the frontend widget emits and ``parse_value_from_input``
        # consumes: ``{"from": {"value": <num>}, "to": {"value": <num>}}`` —
        # either side omittable for an open-ended range.
        if not isinstance(value, dict):
            raise ValueError(
                "NumberRangeFilterWidget expects "
                "{'from': {'value': <number>}, 'to': {'value': <number>}}, "
                f"got {type(value).__name__}: {value!r}"
            )
        for key in ("from", "to"):
            bound = value.get(key)
            if bound is None:
                continue
            if not isinstance(bound, dict):
                raise ValueError(
                    f"NumberRangeFilterWidget {key!r} must be {{'value': <number>}} "
                    f"or omitted, got {bound!r}"
                )
            inner = bound.get("value")
            if inner in (None, ""):
                continue
            try:
                float(inner)
            except (TypeError, ValueError):
                raise ValueError(
                    f"NumberRangeFilterWidget {key!r} value must be a number, "
                    f"got {inner!r}"
                )

    def get_advanced_filter_operators(self):
        return NUMBER_ATTRIBUTES


class DateFilterWidget(SBAdminFilterWidget):
    DATE_RANGE_SPLIT = " - "
    DATE_FORMAT = "%Y-%m-%d"
    template_name = "sb_admin/filter_widgets/date_field.html"
    shortcuts = [
        {"value": [0, 0], "label": _("Today")},
        {
            "value": [-7, 0],
            "label": _("Last 7 days"),
        },
        {
            "value": [-30, 0],
            "label": _("Last 30 days"),
        },
        {
            "value": [-90, 0],
            "label": _("Last 90 days"),
        },
        {
            "value": [-365, 0],
            "label": _("Last 12 months"),
        },
    ]
    shortcuts_dict = {AllOperators.IN_THE_LAST.value: shortcuts}
    default_value_shortcut_index = None

    def __init__(
        self,
        template_name=None,
        default_value=None,
        default_label=None,
        shortcuts=None,
        default_value_shortcut_index=None,
        **kwargs,
    ) -> None:
        super().__init__(template_name, default_value, default_label, **kwargs)
        self.shortcuts = shortcuts or self.shortcuts
        self.default_value_shortcut_index = (
            default_value_shortcut_index
            if default_value_shortcut_index is not None
            else self.default_value_shortcut_index
        )

    def get_advanced_filter_operators(self):
        return DATE_ATTRIBUTES

    def process_shortcut(self, shortcut, now):
        return shortcut

    def get_shortcuts(self):
        now = timezone.now()
        shortcuts = []
        for shortcut in self.shortcuts:
            shortcuts.append(self.process_shortcut(shortcut, now))
        return shortcuts

    def get_shortcuts_dict(self):
        now = timezone.now()
        shortcuts = {}
        for key, shortcuts_group in self.shortcuts_dict.items():
            shortcuts[key] = []
            for shortcut in shortcuts_group:
                shortcuts[key].append(self.process_shortcut(shortcut, now))
        return shortcuts

    def get_default_label(self):
        if self.default_value_shortcut_index is not None:
            return self.get_shortcuts()[self.default_value_shortcut_index]["label"]
        return super().get_default_label()

    def get_default_value(self):
        if self.default_value_shortcut_index is not None:
            selected_shortcut_value = self.get_shortcuts()[
                self.default_value_shortcut_index
            ]["value"]
            return SBAdminViewService.json_dumps_and_replace(
                self.get_value_from_date_or_range(selected_shortcut_value)
            )
        return super().get_default_value()

    def get_data(self):
        return json.dumps(
            {
                "flatpickrOptions": {
                    "locale": {
                        "rangeSeparator": self.DATE_RANGE_SPLIT,
                    },
                },
            },
            cls=SBAdminJSONEncoder,
        )

    def get_shortcuts_data(self):
        return json.dumps(
            self.get_shortcuts(),
            cls=SBAdminJSONEncoder,
        )

    def get_shortcuts_dict_data(self):
        # used for advanced filters with different calendar operators "in the last", "in the next", etc.
        return json.dumps(
            self.get_shortcuts_dict(),
            cls=SBAdminJSONEncoder,
        )

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return isinstance(model_field, fields.DateField)

    @classmethod
    def _days_to_date(cls, days):
        try:
            value = timezone.now() + timedelta(days=int(days))
            return value.replace(hour=0, minute=0, second=0, microsecond=0)
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _parse_date_string(cls, value):
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.strptime(value, cls.DATE_FORMAT)
        except (ValueError, TypeError):
            return None

    @classmethod
    def get_range_from_value(cls, filter_value):
        """Get date-range from string filter value.

        Fail-soft: any malformed input (empty list, non-numeric "in the
        last" magnitudes, unparseable date strings, overflow) returns
        ``[None, None]`` and the caller treats it as "no filter". This
        keeps the list view available instead of 500'ing when a user
        bookmarks a half-typed URL or an attacker probes the operator.

        :returns: ``[date_from, date_to]`` — both entries may be ``None``.
        """
        if filter_value is None:
            return [None, None]
        if isinstance(filter_value, list):
            if len(filter_value) < 2:
                return [None, None]
            first = filter_value[0]
            if isinstance(first, (int, float)):
                return [
                    cls._days_to_date(filter_value[0]),
                    cls._days_to_date(filter_value[1]),
                ]
            return [
                cls._parse_date_string(filter_value[0]),
                cls._parse_date_string(filter_value[1]),
            ]
        if not isinstance(filter_value, str):
            return [None, None]
        try:
            days_range = json.loads(filter_value)
        except (json.JSONDecodeError, ValueError):
            days_range = None
        if isinstance(days_range, list) and len(days_range) >= 2:
            return [cls._days_to_date(days_range[0]), cls._days_to_date(days_range[1])]
        date_range = filter_value.split(cls.DATE_RANGE_SPLIT)
        if len(date_range) == 2:
            return [
                cls._parse_date_string(date_range[0]),
                cls._parse_date_string(date_range[1]),
            ]
        single = cls._parse_date_string(filter_value)
        return [single, single]

    @classmethod
    def get_value_from_date_or_range(cls, date_or_range):
        if not isinstance(date_or_range, (list, tuple)):
            return datetime.strftime(date_or_range, cls.DATE_FORMAT)
        if type(date_or_range[0]) is int:
            return date_or_range
        date_from = datetime.strftime(date_or_range[0], cls.DATE_FORMAT)
        date_to = datetime.strftime(date_or_range[1], cls.DATE_FORMAT)
        return [date_from, date_to]

    # Fail-closed sentinel for invalid filter input. The user submitted a
    # filter rule, so silently dropping it (``Q()``) would show the full
    # table and mislead the user into thinking the filter applied — risky
    # when the resulting set drives bulk actions / exports. ``pk__in=[]``
    # is Django's canonical "match nothing" — the ORM short-circuits it.
    _EMPTY_RESULT_Q = Q(pk__in=[])

    def parse_value_from_input(self, request, filter_value):
        return self.get_range_from_value(filter_value)

    def validate_value(self, value) -> None:
        if not (isinstance(value, list) and len(value) == 2):
            raise ValueError(
                f"DateFilterWidget expects [start, end] (list of 2 ISO date strings), got {type(value).__name__}: {value!r}"
            )
        for v in value:
            if v is None:
                continue
            if not isinstance(v, str):
                raise ValueError(
                    f"DateFilterWidget bounds must be 'YYYY-MM-DD' strings or null, got {v!r}"
                )
            if self._parse_date_string(v) is None:
                raise ValueError(
                    f"DateFilterWidget bound {v!r} is not a valid ISO-8601 date"
                )

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        if not filter_value:
            return self._EMPTY_RESULT_Q
        date_from, date_to = filter_value[0], filter_value[1]
        # Only both-null means "no usable filter" → match nothing. A single
        # bound is a valid open-ended range (``>= from`` or ``<= to``).
        if date_from is None and date_to is None:
            return self._EMPTY_RESULT_Q
        query = Q()
        if date_from is not None:
            query &= Q(**{f"{self.field.filter_field}__gte": date_from})
        if date_to is not None:
            # add one day to include all 'to' date hours, this is needed
            # instead of casting datetime to date in DB
            query &= Q(
                **{f"{self.field.filter_field}__lte": date_to + timedelta(days=1)}
            )
        return query

    def get_advanced_filter_query_for_parsed_value(
        self, request, parsed_value, original_query, rule
    ):
        # Caller built ``Q(field__range=[None, None])`` which would 500 at
        # SQL. Replace with ``pk__in=[]`` so the response is an empty (but
        # safe) result set — the user still sees their filter is active
        # but no spurious rows leak through.
        if not parsed_value or all(v is None for v in parsed_value):
            return self._EMPTY_RESULT_Q
        return original_query


class AutocompleteFilterWidget(
    AutocompleteParseMixin, SBAdminView, SBAdminFilterWidget
):
    template_name = "sb_admin/filter_widgets/autocomplete_field.html"
    autocomplete_url = None
    multiselect = None
    value_field = None
    filter_search_lambda = None
    model = None
    forward = None
    label_lambda = None
    value_lambda = None
    hide_clear_button = False
    search_query_lambda = None
    create_value_field = None

    def get_field_name(self):
        return self.field.name

    def get_id(self):
        return f"{self.view.get_id()}_{self.get_field_name()}_{self.__class__.__name__}"

    def __init__(
        self,
        template_name=None,
        default_value=None,
        model=None,
        value_field=None,
        filter_query_lambda=None,
        filter_search_lambda=None,
        label_lambda=None,
        value_lambda=None,
        multiselect=None,
        forward=None,
        hide_clear_button=None,
        search_query_lambda=None,
        **kwargs,
    ) -> None:
        super().__init__(template_name, default_value, **kwargs)
        self.model = model or self.model
        self.value_field = value_field or self.value_field
        self.filter_query_lambda = filter_query_lambda or self.filter_query_lambda
        # filters queryset to search in
        self.filter_search_lambda = filter_search_lambda or self.filter_search_lambda
        # defines fields to search on
        self.search_query_lambda = search_query_lambda or self.search_query_lambda
        self.label_lambda = label_lambda or self.label_lambda
        self.value_lambda = value_lambda or self.value_lambda
        self.multiselect = multiselect if multiselect is not None else self.multiselect
        self.multiselect = self.multiselect if self.multiselect is not None else True
        self.forward = forward or self.forward
        self.hide_clear_button = (
            hide_clear_button
            if hide_clear_button is not None
            else self.hide_clear_button
        )

    def init_filter_widget_static(self, field, view, configuration):
        super().init_filter_widget_static(field, view, configuration)
        self.init_autocomplete_widget_static(
            field.name, self.model or self.model_field.target_field.model, configuration
        )

    def init_autocomplete_widget_static(self, field_name, model, configuration):
        if not model:
            raise ImproperlyConfigured(
                f"For '{field_name}' defined in '{self}', model needs to be specified for AutocompleteFilterWidget."
            )
        self.model = model

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return (
            isinstance(model_field, fields.reverse_related.ManyToOneRel)
            or isinstance(model_field, fields.related.ForeignKey)
            or isinstance(model_field, fields.related.ManyToManyField)
        )

    def get_autocomplete_url(self):
        return self.view.get_action_url(
            Action.AUTOCOMPLETE.value, modifier=self.get_id()
        )

    @sbadmin_action(permission="view")
    def action_autocomplete(self, request, modifier, object_id=None):
        result = self.search(request, request.request_data.request_post)
        return JsonResponse({"data": result})

    def to_json(self):
        data = super().to_json()
        data.update(
            {
                "autocomplete_url": self.get_autocomplete_url(),
                "forward": self.forward,
                "field_name": self.get_field_name(),
                "constants": {
                    "autocomplete_term": AUTOCOMPLETE_SEARCH_NAME,
                    "autocomplete_forward": AUTOCOMPLETE_FORWARD_NAME,
                    "autocomplete_requested_page": AUTOCOMPLETE_PAGE_NUM,
                },
            }
        )
        return data

    def get_base_filter_query_for_parsed_value(self, request, parsed_value):
        return Q(**{f"{self.field.filter_field}__in": parsed_value})

    def validate_value(self, value) -> None:
        if not isinstance(value, list):
            raise ValueError(
                f"AutocompleteFilterWidget expects a list of {{'value', 'label'}} entries, got {type(value).__name__}: {value!r}"
            )
        for entry in value:
            if not (isinstance(entry, dict) and "value" in entry):
                raise ValueError(
                    f"AutocompleteFilterWidget entries must be {{'value': <pk>, 'label': <str>}}, got {entry!r}"
                )

    @classmethod
    def should_add_query(cls, model_field, search_term, numeric_term):
        search_string = search_term and (
            isinstance(model_field, fields.CharField)
            or isinstance(model_field, fields.TextField)
        )
        search_numeric = numeric_term and (
            isinstance(model_field, fields.AutoField)
            or isinstance(model_field, fields.IntegerField)
            or isinstance(model_field, fields.DecimalField)
        )
        return search_string or search_numeric

    @classmethod
    def get_default_search_query(
        cls, request, queryset, model, search_term, language_code
    ):
        numeric_term = None
        annotate = {}
        try:
            numeric_term = float(search_term)
        except ValueError:
            pass
        search_query = Q()
        for model_field in model._meta.get_fields():
            if cls.should_add_query(model_field, search_term, numeric_term):
                search_query |= Q(**{f"{model_field.name}__icontains": search_term})
        if SBAdminTranslationsService.is_translated_model(model):
            for (
                field_name,
                translation_model,
            ) in model._parler_meta.get_fields_with_model():
                annotate_name = str(
                    f"{translation_model._meta.db_table}_{language_code}"
                )
                rel_name = model._parler_meta[translation_model].rel_name
                annotate[annotate_name] = FilteredRelation(
                    rel_name,
                    condition=Q(**{f"{rel_name}__language_code": language_code}),
                )
                model_field = translation_model._meta.get_field(field_name)
                if cls.should_add_query(model_field, search_term, numeric_term):
                    search_query |= Q(
                        **{
                            f"{annotate_name}__{model_field.name}__icontains": search_term
                        }
                    )
        return queryset.annotate(**annotate).filter(search_query)

    def get_value_field(self):
        return self.value_field or self.model._meta.pk.name

    def filter_search_queryset(self, request, qs, search_term="", forward_data=None):
        if self.filter_search_lambda:
            forward_data = forward_data or {}
            qs = qs.filter(
                self.filter_search_lambda(request, search_term, forward_data)
            )
        return qs

    def search(self, request, post_data):
        search_term = post_data.get(AUTOCOMPLETE_SEARCH_NAME)
        forward_data = json.loads(post_data.get(AUTOCOMPLETE_FORWARD_NAME, "{}"))
        page_num = int(post_data.get(AUTOCOMPLETE_PAGE_NUM, 1))
        from_item = (page_num - 1) * AUTOCOMPLETE_PAGE_SIZE
        to_item = (page_num) * AUTOCOMPLETE_PAGE_SIZE

        # filter queryset
        # base restricted queryset
        qs = self.get_queryset(request)
        # filters queryset to search in, uses filter_search_lambda
        qs = self.filter_search_queryset(request, qs, search_term, forward_data)

        # search in queryset
        if self.search_query_lambda:
            # defines fields to search on
            qs = self.search_query_lambda(
                request,
                qs,
                self.model,
                search_term,
                SBAdminTranslationsService.get_main_lang_code(),
            )
        else:
            # defines default fields to search on - all char fields
            qs = self.get_default_search_query(
                request,
                qs,
                self.model,
                search_term,
                SBAdminTranslationsService.get_main_lang_code(),
            )

        qs = qs[from_item:to_item]
        result = []
        for item in qs:
            result.append(
                {
                    "value": self.get_value(request, item),
                    "label": self.get_label(request, item),
                }
            )
        return result

    def get_value(self, request, item):
        if self.value_lambda:
            return self.value_lambda(request, item)
        return getattr(item, self.get_value_field())

    def get_label(self, request, item):
        if self.label_lambda:
            return self.label_lambda(request, item)
        if isinstance(item, list):
            return ", ".join(map(str, item))
        return str(item)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["filter_widget"] = self
        context["widget"]["type"] = "hidden"
        context["widget"]["attrs"]["id"] = (
            self.input_id or context["widget"]["attrs"]["id"]
        )
        return context

    def get_advanced_filter_operators(self):
        return [
            AllOperators.IN,
            AllOperators.NOT_IN,
            AllOperators.IS_NULL,
            AllOperators.IS_NOT_NULL,
        ]


class FromValuesAutocompleteWidget(AutocompleteFilterWidget):
    def init_filter_widget_static(self, field, view, configuration):
        self.model = field.view.model
        super().init_filter_widget_static(field, view, configuration)

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        qs = qs.annotate(**self.field.get_field_annotates(values=[]))
        return qs

    def search(self, request, post_data):
        search_term = post_data.get(AUTOCOMPLETE_SEARCH_NAME)
        forward_data = json.loads(post_data.get(AUTOCOMPLETE_FORWARD_NAME, "{}"))
        page_num = int(post_data.get(AUTOCOMPLETE_PAGE_NUM, 1))
        from_item = (page_num - 1) * AUTOCOMPLETE_PAGE_SIZE
        to_item = (page_num) * AUTOCOMPLETE_PAGE_SIZE
        qs = self.get_queryset(request)
        qs = self.filter_search_queryset(request, qs, search_term, forward_data)
        qs = (
            qs.filter(**{f"{self.field.name}__icontains": search_term})
            .values(self.field.name)
            .annotate(remove_duplicates_count=Count(self.field.name))
            .order_by(self.field.name)[from_item:to_item]
        )
        result = []
        for item in qs:
            result.append(
                {
                    "value": self.get_value(request, item),
                    "label": self.get_label(request, item),
                }
            )
        return result

    def get_value(self, request, item):
        return item.get(self.field.name)

    def get_label(self, request, item):
        return item.get(self.field.name)


class SBAdminTreeWidgetMixin:
    order_by = None
    inline = False
    RELATIONSHIP_PICK_MODE_NONE = None
    RELATIONSHIP_PICK_MODE_PARENT = "parent"
    relationship_pick_mode = RELATIONSHIP_PICK_MODE_NONE
    additional_columns = None
    tree_strings = {
        "loading": pgettext_lazy("Tree widget", "Loading..."),
        "loadError": pgettext_lazy("Tree widget", "Load error!"),
        "moreData": pgettext_lazy("Tree widget", "More..."),
        "noData": pgettext_lazy("Tree widget", "No data."),
    }
    model = None
    path_field = "path"

    def __init__(
        self,
        order_by=None,
        relationship_pick_mode=None,
        inline=None,
        additional_columns=None,
        tree_strings=None,
        *args,
        **kwargs,
    ):
        self.inline = inline if inline is not None else self.inline
        self.order_by = order_by if order_by is not None else self.order_by
        self.relationship_pick_mode = relationship_pick_mode
        self.additional_columns = (
            additional_columns
            if additional_columns is not None
            else self.additional_columns
        )
        self.tree_strings = (
            tree_strings if tree_strings is not None else self.tree_strings
        )
        if self.inline:
            self.template_name = "sb_admin/widgets/tree_select_inline.html"
        super().__init__(*args, **kwargs)

    @sbadmin_action(permission="view")
    def action_autocomplete(self, request, modifier, object_id=None):
        result = self.format_tree_data(request, self.get_queryset(request))
        return JsonResponse(data=result, safe=False)

    def format_tree_data(self, request, queryset):
        self_id = None
        if self.relationship_pick_mode == self.RELATIONSHIP_PICK_MODE_PARENT:
            # disable selecting self and children if selecting parent
            self_id = self.form.instance.id if self.form.instance else None
        return self.get_tree_data(request, queryset, self_id=self_id)

    @classmethod
    def get_tree_base_values(cls):
        return ["id", cls.path_field]

    @classmethod
    def get_tree_key(cls, request, item):
        return item.get(cls.path_field)

    @classmethod
    def get_tree_title(cls, request, item):
        raise NotImplementedError

    @classmethod
    def get_value(cls, request, item):
        return getattr(item, cls.path_field)

    @classmethod
    def get_label(cls, request, item):
        raise NotImplementedError

    @classmethod
    def tree_process_global_data(cls, request, queryset, **kwargs):
        return {}

    @classmethod
    def get_additional_data(cls, request, item, tree_process_global_data):
        return {}

    @classmethod
    def get_tree_data(cls, request, queryset, values=None, self_id=None, **kwargs):
        tree_values = cls.get_tree_base_values()
        tree_values.extend(values if values else [])

        queryset = queryset.order_by(*cls.order_by)
        queryset = queryset.annotate(
            **SBAdminViewService.get_annotates(cls.model, tree_values, [])
        )
        flat_data = []
        tree_data, lnk = [], {}
        tree_process_global_data = cls.tree_process_global_data(
            request, queryset, **kwargs
        )

        data = list(queryset.values(*tree_values))
        for item in data:
            path = item.get("path")
            depth = int(len(path) / cls.model.steplen)
            item_id = cls.get_tree_key(request, item)
            item_label = cls.get_tree_title(request, item)
            newobj = {
                "title": item_label,
                "key": str(item_id),
                "data": {"id": item.get("id")},
            }
            if item_id == self_id:
                # disable selecting self and children if selecting parent
                newobj["checkbox"] = False

            additional_data = cls.get_additional_data(
                request, item, tree_process_global_data
            )
            newobj.update(additional_data)

            if depth == 1:
                tree_data.append(newobj)
                flat_data.append(newobj)
            else:
                parentpath = cls.model._get_basepath(path, depth - 1)
                parentobj = lnk[parentpath]
                if "children" not in parentobj:
                    parentobj["children"] = []
                if parentobj.get("checkbox") is False:
                    # disable selecting self and children if selecting parent
                    newobj["checkbox"] = False
                parentobj["children"].append(newobj)
                flat_data.append(newobj)
            lnk[path] = newobj
        return tree_data

    # tree_widget_data: [{"key":"path", "children": [{...}]}]
    @classmethod
    def process_treebeard_tree(
        cls,
        tree_widget_data,
        treebeard_objs_by_path,
        depth=1,
        parent_path="",
        path_base="",
    ):
        if not path_base:
            path_base = ((cls.model.steplen - 1) * "0") + "1"
        previous = None
        objs_to_update = []
        for tree_widget_node in tree_widget_data:
            treebeard_obj = treebeard_objs_by_path.get(tree_widget_node["key"])
            old_depth = treebeard_obj.depth
            old_path = getattr(treebeard_obj, cls.path_field)
            old_numchild = treebeard_obj.numchild
            treebeard_obj.depth = depth
            if not previous:
                previous = treebeard_obj
                setattr(treebeard_obj, cls.path_field, parent_path + path_base)
            else:
                setattr(treebeard_obj, cls.path_field, previous._inc_path())
                previous = treebeard_obj
            children = tree_widget_node.get("children", [])
            treebeard_obj.numchild = len(children)
            if (
                treebeard_obj.depth != old_depth
                or getattr(treebeard_obj, cls.path_field) != old_path
                or treebeard_obj.numchild != old_numchild
            ):
                objs_to_update.append(treebeard_obj)
            objs_to_update.extend(
                cls.process_treebeard_tree(
                    children,
                    treebeard_objs_by_path,
                    depth + 1,
                    getattr(treebeard_obj, cls.path_field),
                    path_base,
                )
            )
        return objs_to_update


class SBAdminTreeFilterWidget(SBAdminTreeWidgetMixin, AutocompleteFilterWidget):
    template_name = "sb_admin/filter_widgets/tree_select_filter.html"
