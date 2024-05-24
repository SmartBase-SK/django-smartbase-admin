import copy
import json
from dataclasses import dataclass, asdict
from dataclasses import field as dataclass_field
from enum import Enum
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string

from django_smartbase_admin.engine.const import ADVANCED_FILTER_DATA_NAME

if TYPE_CHECKING:
    from django_smartbase_admin.engine.filter_widgets import (
        SBAdminFilterWidget,
    )

QB_JS_PREFIX = "SB_REPLACE_ME"
QB_JS_SEPARATOR = "__"


class QueryBuilderFilterType(Enum):
    STRING = "string"
    INTEGER = "integer"
    DOUBLE = "double"
    DATE = "date"
    TIME = "time"
    DATETIME = "datetime"
    BOOLEAN = "boolean"


class AllOperators(models.TextChoices):
    EQUAL = "equal", _("Equal")
    NOT_EQUAL = "not_equal", _("Not equal")
    LESS = "less", _("Less")
    LESS_OR_EQUAL = "less_or_equal", _("Less or equal")
    GREATER = "greater", _("Greater")
    GREATER_OR_EQUAL = "greater_or_equal", _("Greater or equal")
    BETWEEN = "between", _("Between")
    NOT_BETWEEN = "not_between", _("Not between")
    IN = "in", _("In")
    NOT_IN = "not_in", _("Not in")
    BEGINS_WITH = "begins_with", _("Begins with")
    NOT_BEGINS_WITH = "not_begins_with", _("Not begins with")
    CONTAINS = "contains", _("Contains")
    NOT_CONTAINS = "not_contains", _("Not contains")
    ENDS_WITH = "ends_with", _("End with")
    NOT_ENDS_WITH = "not_ends_with", _("Not ends with")
    IS_EMPTY = "is_empty", _("Is empty")
    IS_NOT_EMPTY = "is_not_empty", _("Equal")
    IS_NULL = "is_null", _("Is null")
    IS_NOT_NULL = "is_not_null", _("Is not null")


ZERO_INPUTS_OPERATORS = {
    AllOperators.IS_EMPTY.value,
    AllOperators.IS_NOT_EMPTY.value,
    AllOperators.IS_NULL.value,
    AllOperators.IS_NOT_NULL.value,
}

NUMBER_ATTRIBUTES = [
    AllOperators.BETWEEN,
    AllOperators.NOT_BETWEEN,
    AllOperators.LESS,
    AllOperators.LESS_OR_EQUAL,
    AllOperators.GREATER,
    AllOperators.GREATER_OR_EQUAL,
    AllOperators.IS_NULL,
    AllOperators.IS_NOT_NULL,
]

STRING_ATTRIBUTES = [
    AllOperators.EQUAL,
    AllOperators.NOT_EQUAL,
    AllOperators.CONTAINS,
    AllOperators.NOT_CONTAINS,
    AllOperators.BEGINS_WITH,
    AllOperators.NOT_BEGINS_WITH,
    AllOperators.ENDS_WITH,
    AllOperators.NOT_ENDS_WITH,
    AllOperators.IS_EMPTY,
    AllOperators.IS_NOT_EMPTY,
]


@dataclass
class QueryBuilderFilter:
    id: str
    type: str
    field: Optional[str] = None
    label: Optional[str] = None
    input: Optional[str] = None
    default_value: Optional[Any] = None
    input_event: Optional[str] = "change"
    multiple: Optional[bool] = False
    placeholder: Optional[str] = None
    validation: Optional[Dict[str, Any]] = dataclass_field(default_factory=dict)
    operators: Optional[List[str]] = dataclass_field(default_factory=list)
    default_operator: Optional[str] = None
    plugin: Optional[str] = None
    plugin_config: Optional[Dict[str, Any]] = dataclass_field(default_factory=dict)
    data: Optional[Dict[str, Any]] = dataclass_field(default_factory=dict)

    @classmethod
    def from_filter_widget(cls, filter_widget: "SBAdminFilterWidget"):
        from django_smartbase_admin.engine.filter_widgets import (
            SBAdminFilterWidget,
            AutocompleteFilterWidget,
            DateFilterWidget,
        )

        widget_to_querybuilder_plugin = {
            AutocompleteFilterWidget: "SBAutocomplete",
            DateFilterWidget: "SBDate",
        }

        filter_widget_for_context = copy.copy(filter_widget)
        filter_widget_for_context.input_id = QB_JS_PREFIX
        filter_widget_for_context.input_name = QB_JS_PREFIX
        querybuilder_plugin = None
        for widget_class, plugin in widget_to_querybuilder_plugin.items():
            if isinstance(filter_widget, widget_class):
                querybuilder_plugin = plugin
                break
        operators = filter_widget.get_advanced_filter_operators()
        operators = [operator.value for operator in operators]
        return cls(
            id=filter_widget.input_id,
            label=filter_widget.field.title,
            type=QueryBuilderFilterType.STRING.value,
            plugin=querybuilder_plugin,
            operators=operators,
            input=render_to_string(
                template_name=filter_widget.template_name.replace(
                    "filter_widgets/", "filter_widgets/advanced_filters/"
                ),
                context={
                    "filter_widget": filter_widget_for_context,
                    "prefix_to_replace": QB_JS_PREFIX,
                },
            ).replace("</script>", "<\/script>"),
        )


@dataclass
class QueryBuilderData:
    filters: Optional[List[QueryBuilderFilter]] = dataclass_field(default_factory=list)
    current_rules: str = ""
    all_operators: str = ""
    operators_translations: str = ""
    prefix_to_replace: str = QB_JS_PREFIX
    prefix_separator: str = QB_JS_SEPARATOR


class QueryBuilderService:
    # Map QueryBuilder operators to Django ORM lookups
    operator_map = {
        AllOperators.EQUAL.value: "__exact",
        AllOperators.NOT_EQUAL.value: "__exact",
        AllOperators.LESS.value: "__lt",
        AllOperators.LESS_OR_EQUAL.value: "__lte",
        AllOperators.GREATER.value: "__gt",
        AllOperators.GREATER_OR_EQUAL.value: "__gte",
        AllOperators.BETWEEN.value: "__range",
        AllOperators.NOT_BETWEEN.value: "__range",
        AllOperators.IN.value: "__in",
        AllOperators.NOT_IN.value: "__in",
        AllOperators.BEGINS_WITH.value: "__startswith",
        AllOperators.NOT_BEGINS_WITH.value: "__startswith",
        AllOperators.CONTAINS.value: "__icontains",
        AllOperators.NOT_CONTAINS.value: "__icontains",
        AllOperators.ENDS_WITH.value: "__endswith",
        AllOperators.NOT_ENDS_WITH.value: "__endswith",
        AllOperators.IS_EMPTY.value: "__exact",
        AllOperators.IS_NOT_EMPTY.value: "__exact",
        AllOperators.IS_NULL.value: "__isnull",
        AllOperators.IS_NOT_NULL.value: "__isnull",
    }

    negative_operators = [
        AllOperators.NOT_IN.value,
        AllOperators.NOT_EQUAL.value,
        AllOperators.NOT_BEGINS_WITH.value,
        AllOperators.NOT_CONTAINS.value,
        AllOperators.NOT_ENDS_WITH.value,
        AllOperators.IS_NOT_EMPTY.value,
        AllOperators.IS_NOT_NULL.value,
    ]

    @classmethod
    def querybuilder_to_django_filter(
        cls, request, view_id: str, column_fields: dict, query: dict
    ) -> [Q, list]:
        all_fields = []

        # Recursively build the Q object
        def build_q(rules, condition):
            queries = []
            for rule in rules:
                if "condition" in rule:
                    # Nested group of rules
                    sub_q = build_q(rule["rules"], rule["condition"])
                    queries.append(sub_q)
                    continue

                # Single rule
                field_name = rule["field"].replace(f"{view_id}-", "")
                field = column_fields.get(field_name)
                operator = rule["operator"]
                if field is None:
                    continue

                value = field.filter_widget.parse_value_from_input(
                    request, rule["value"]
                )
                all_fields.append(field)

                if operator in ZERO_INPUTS_OPERATORS:
                    q = Q(
                        **{
                            f"{field.filter_field}{cls.operator_map[operator]}": (
                                True
                                if operator
                                in [AllOperators.IS_NULL, AllOperators.IS_NOT_NULL]
                                else ""
                            ),
                        }
                    )
                else:
                    q = Q(
                        **{f"{field.filter_field}{cls.operator_map[operator]}": value}
                    )

                if operator in cls.negative_operators:
                    q = ~q

                queries.append(q)

            if condition == "AND":
                return Q(*queries)
            else:  # condition == "OR"
                return Q(*queries, _connector=Q.OR)

        return build_q(query["rules"], query["condition"]), all_fields

    @classmethod
    def get_filters_for_list_action(cls, list_action):
        querybuilder_filters = list_action.params.get(ADVANCED_FILTER_DATA_NAME, {})
        if not querybuilder_filters:
            return Q()
        view_id = list_action.view.get_id()
        column_fields = {field.field: field for field in list_action.column_fields}
        query, _ = cls.querybuilder_to_django_filter(
            list_action.threadsafe_request,
            view_id,
            column_fields,
            querybuilder_filters,
        )
        return query

    @classmethod
    def get_filters_fields_for_list_action(cls, list_action):
        querybuilder_filters = list_action.params.get(ADVANCED_FILTER_DATA_NAME, {})
        if not querybuilder_filters:
            return []
        view_id = list_action.view.get_id()
        column_fields = {field.field: field for field in list_action.column_fields}
        _, fields = cls.querybuilder_to_django_filter(
            list_action.threadsafe_request,
            view_id,
            column_fields,
            querybuilder_filters,
        )
        return fields

    @classmethod
    def get_all_operators_for_query_builder(cls):
        all_operators = {
            key: str(label) for key, label in dict(AllOperators.choices).items()
        }
        operators = []
        operators_translations = all_operators
        for key, label in all_operators.items():
            if key in ZERO_INPUTS_OPERATORS:
                number_of_inputs = 0
            else:
                number_of_inputs = 1
            operators.append({"type": key, "nb_inputs": number_of_inputs})
        return json.dumps(operators), json.dumps(operators_translations)

    @classmethod
    def get_advanced_filters_context_data(cls, list_action):
        filters = []
        for column_field in list_action.column_fields:
            if not column_field.filter_widget:
                continue

            filters.append(
                QueryBuilderFilter.from_filter_widget(column_field.filter_widget)
            )
        current_rules = list_action.params.get(ADVANCED_FILTER_DATA_NAME, {})
        current_rules = (
            json.dumps(list_action.params.get(ADVANCED_FILTER_DATA_NAME, {}))
            if current_rules
            else ""
        )
        operators, operators_translations = cls.get_all_operators_for_query_builder()
        return asdict(
            QueryBuilderData(
                filters=filters,
                current_rules=current_rules,
                all_operators=operators,
                operators_translations=operators_translations,
            )
        )
