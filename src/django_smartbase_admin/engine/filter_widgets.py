import json
from datetime import datetime, timedelta

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, fields, FilteredRelation
from django.http import JsonResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.advanced_filters import (
    AllOperators,
    STRING_ATTRIBUTES,
    NUMBER_ATTRIBUTES,
)
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import (
    AUTOCOMPLETE_SEARCH_NAME,
    AUTOCOMPLETE_PAGE_SIZE,
    Action,
    AUTOCOMPLETE_PAGE_NUM,
    AUTOCOMPLETE_FORWARD_NAME,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder
from django_smartbase_admin.utils import JSONSerializableMixin


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

    def __init__(
        self,
        template_name=None,
        default_value=None,
        default_label=None,
        filter_query_lambda=None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.template_name = self.template_name or template_name
        self.default_value = self.default_value or default_value
        self.default_label = self.default_label or default_label
        self.filter_query_lambda = filter_query_lambda or self.filter_query_lambda

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

    def get_filter_query_for_value(self, request, filter_value):
        parsed_value = self.parse_value_from_input(request, filter_value)
        if self.filter_query_lambda:
            return self.filter_query_lambda(request, parsed_value)
        return self.get_base_filter_query_for_parsed_value(request, parsed_value)

    def get_base_filter_query_for_parsed_value(self, request, parsed_value):
        return Q(**{f"{self.field.filter_field}__icontains": parsed_value})

    def to_json(self):
        return {"input_id": self.input_id}

    def get_default_value(self):
        return self.default_value

    def get_default_label(self):
        return self.default_label or self.get_default_value()

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return False

    @classmethod
    def apply_to_field(cls, field):
        return cls.apply_to_model_field(field.model_field)

    @classmethod
    def apply_to_model_field(cls, model_field):
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
        ]


class StringFilterWidget(SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/string_field.html"

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

    def get_advanced_filter_operators(self):
        return [
            AllOperators.EQUAL,
            AllOperators.NOT_EQUAL,
        ]

    def parse_value_from_input(self, request, filter_value):
        value = super().parse_value_from_input(request, filter_value)
        return json.loads(value)

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return isinstance(model_field, fields.BooleanField)

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        return Q(**{f"{self.field.filter_field}": filter_value})


class ChoiceFilterWidget(SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/choice_field.html"
    choices = None

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

    def get_advanced_filter_operators(self):
        return [
            AllOperators.EQUAL,
            AllOperators.NOT_EQUAL,
        ]

    def get_default_label(self):
        if self.default_label:
            return self.default_label
        else:
            default_value = self.get_default_value()
            found_label = [
                label for value, label in self.choices if value == default_value
            ]
            return found_label[0] if found_label else default_value

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        return Q(**{self.field.filter_field: filter_value})


class RadioChoiceFilterWidget(ChoiceFilterWidget):
    template_name = "sb_admin/filter_widgets/radio_choice_field.html"


class MultipleChoiceFilterWidget(AutocompleteParseMixin, ChoiceFilterWidget):
    template_name = "sb_admin/filter_widgets/multiple_choice_field.html"

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        return Q(**{f"{self.field.filter_field}__in": filter_value})

    def get_advanced_filter_operators(self):
        return [
            AllOperators.IN,
            AllOperators.NOT_IN,
        ]


class NumberRangeFilterWidget(AutocompleteParseMixin, SBAdminFilterWidget):
    template_name = "sb_admin/filter_widgets/number_range_field.html"

    def parse_value_from_input(self, request, filter_value):
        filter_value = super().parse_value_from_input(request, filter_value)
        from_value = filter_value.get("from", {}).get("value", None)
        to_value = filter_value.get("to", {}).get("value", None)
        return [from_value, to_value]

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        result = Q()
        if filter_value[0] is not None:
            result &= Q(**{f"{self.field.filter_field}__gte": filter_value[0]})
        if filter_value[1] is not None:
            result &= Q(**{f"{self.field.filter_field}__lte": filter_value[1]})
        return result

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
        return NUMBER_ATTRIBUTES

    def get_shortcuts(self):
        now = timezone.now()
        shortcuts = []
        for shortcut in self.shortcuts:
            shortcuts.append(
                {
                    "label": shortcut["label"],
                    "value": [
                        now + timedelta(days=shortcut["value"][0]),
                        now + timedelta(days=shortcut["value"][1]),
                    ],
                }
            )
        return shortcuts

    def get_default_value(self):
        if self.default_value_shortcut_index is not None:
            selected_shortcut_value = self.get_shortcuts()[
                self.default_value_shortcut_index
            ]["value"]
            return self.get_value_from_date_or_range(selected_shortcut_value)
        return super().get_default_value()

    def get_data(self):
        return json.dumps(
            {
                "shortcuts": self.get_shortcuts(),
                "flatpickrOptions": {
                    "locale": {
                        "rangeSeparator": self.DATE_RANGE_SPLIT,
                    }
                },
            },
            cls=SBAdminJSONEncoder,
        )

    @classmethod
    def is_used_for_model_field_type(cls, model_field):
        return isinstance(model_field, fields.DateField)

    @classmethod
    def get_date_or_range_from_value(cls, filter_value):
        """
        Get single date or date-range from string filter value

        :returns: date or array or dates, is_range
        """
        if filter_value is None:
            return [None, None], False
        date_format = cls.DATE_FORMAT
        date_range = filter_value.split(cls.DATE_RANGE_SPLIT)
        if len(date_range) == 2:
            date_from = datetime.strptime(date_range[0], date_format)
            date_to = datetime.strptime(date_range[1], date_format)
            return [date_from, date_to], True
        else:
            date_value = datetime.strptime(filter_value, date_format)
            return date_value, False

    @classmethod
    def get_value_from_date_or_range(cls, date_or_range):
        if not isinstance(date_or_range, list):
            return datetime.strftime(date_or_range, cls.DATE_FORMAT)
        date_from = datetime.strftime(date_or_range[0], cls.DATE_FORMAT)
        date_to = datetime.strftime(date_or_range[1], cls.DATE_FORMAT)
        return f"{date_from}{cls.DATE_RANGE_SPLIT}{date_to}"

    def parse_value_from_input(self, request, filter_value):
        date_or_range, _ = self.get_date_or_range_from_value(filter_value)
        return date_or_range

    def get_base_filter_query_for_parsed_value(self, request, filter_value):
        date_or_range, is_range = self.get_date_or_range_from_value(filter_value)
        if is_range:
            date_from = date_or_range[0]
            # add one day to include all 'to' date hours, this is needed instead of casting datetime to date in DB
            date_to = date_or_range[1] + timedelta(days=1)
            return Q(
                **{
                    f"{self.field.filter_field}__gte": date_from,
                    f"{self.field.filter_field}__lte": date_to,
                }
            )
        else:
            date_value = date_or_range
            # TODO date_or_range je vzdy pole o dvoch ? ak ano tak tuna sa da pole mozno chyba...
            return Q(**{f"{self.field.filter_field}": date_value})


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
    allow_add = False
    hide_clear_button = False

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
        allow_add=None,
        hide_clear_button=None,
        **kwargs,
    ) -> None:
        super().__init__(template_name, default_value, **kwargs)
        self.model = model or self.model
        self.value_field = value_field or self.value_field
        self.filter_query_lambda = filter_query_lambda or self.filter_query_lambda
        self.filter_search_lambda = filter_search_lambda or self.filter_search_lambda
        self.label_lambda = label_lambda or self.label_lambda
        self.value_lambda = value_lambda or self.value_lambda
        self.multiselect = multiselect if multiselect is not None else self.multiselect
        self.multiselect = self.multiselect if self.multiselect is not None else True
        self.forward = forward or self.forward
        self.allow_add = allow_add or self.allow_add
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
        configuration.dynamically_register_autocomplete_view(self)
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

    def action_autocomplete(self, request, modifier):
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

    def filter_search_queryset(self, request, qs, search_term, forward_data):
        if self.filter_search_lambda:
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
        qs = self.get_queryset(request)
        qs = self.filter_search_queryset(request, qs, search_term, forward_data)
        qs = self.get_default_search_query(
            request,
            qs,
            self.model,
            search_term,
            SBAdminTranslationsService.get_main_lang_code(),
        )[from_item:to_item]
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
        return str(item)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["filter_widget"] = self
        context["widget"]["type"] = "hidden"
        context["widget"]["attrs"]["id"] = self.input_id
        return context

    def get_advanced_filter_operators(self):
        return [
            AllOperators.IN,
            AllOperators.NOT_IN,
            AllOperators.IS_NULL,
            AllOperators.IS_NOT_NULL,
        ]
