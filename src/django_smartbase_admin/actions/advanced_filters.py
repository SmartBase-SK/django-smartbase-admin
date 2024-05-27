import copy
import json
from dataclasses import dataclass, asdict
from dataclasses import field as dataclass_field
from typing import List, Optional, TYPE_CHECKING

from django.db import models
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.engine.const import ADVANCED_FILTER_DATA_NAME

if TYPE_CHECKING:
    from django_smartbase_admin.engine.filter_widgets import (
        SBAdminFilterWidget,
    )

QB_JS_PREFIX = "SB_REPLACE_ME"


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
    type: str = "string"
    label: Optional[str] = None
    input: Optional[str] = None
    operators: Optional[List[str]] = dataclass_field(default_factory=list)

    @classmethod
    def from_filter_widget(cls, filter_widget: "SBAdminFilterWidget"):
        filter_widget_for_context = copy.copy(filter_widget)
        filter_widget_for_context.input_id = QB_JS_PREFIX
        filter_widget_for_context.input_name = QB_JS_PREFIX
        operators = filter_widget.get_advanced_filter_operators()
        operators = [operator.value for operator in operators]
        return cls(
            id=filter_widget.input_id,
            label=filter_widget.field.title,
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


class QueryBuilderService:
    # Map QueryBuilder operators to Django ORM lookups
    OPERATOR_MAP = {
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

    ZERO_INPUTS_OPERATORS = {
        AllOperators.IS_EMPTY.value,
        AllOperators.IS_NOT_EMPTY.value,
        AllOperators.IS_NULL.value,
        AllOperators.IS_NOT_NULL.value,
    }

    NEGATIVE_OPERATORS = [
        AllOperators.NOT_IN.value,
        AllOperators.NOT_EQUAL.value,
        AllOperators.NOT_BEGINS_WITH.value,
        AllOperators.NOT_CONTAINS.value,
        AllOperators.NOT_ENDS_WITH.value,
        AllOperators.IS_NOT_EMPTY.value,
        AllOperators.IS_NOT_NULL.value,
    ]

    LIST_OPERATORS = [
        AllOperators.NOT_IN.value,
        AllOperators.IN.value,
        AllOperators.BETWEEN.value,
        AllOperators.NOT_BETWEEN.value,
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

                if rule["field"] is None or "value" not in rule:
                    # rule is not valid skip
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
                if operator not in cls.LIST_OPERATORS and isinstance(value, list):
                    value = value[0]

                all_fields.append(field)

                if operator in cls.ZERO_INPUTS_OPERATORS:
                    filter_value = (
                        True
                        if operator in [AllOperators.IS_NULL, AllOperators.IS_NOT_NULL]
                        else ""
                    )
                    q = Q(
                        **{
                            f"{field.filter_field}{cls.OPERATOR_MAP[operator]}": filter_value,
                        }
                    )
                else:
                    q = Q(
                        **{f"{field.filter_field}{cls.OPERATOR_MAP[operator]}": value}
                    )

                if operator in cls.NEGATIVE_OPERATORS:
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
            if key in cls.ZERO_INPUTS_OPERATORS:
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
