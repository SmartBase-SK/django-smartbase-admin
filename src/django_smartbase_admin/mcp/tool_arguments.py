"""Typed, described arguments for the SBAdmin MCP tools.

FastMCP builds each tool's ``inputSchema`` from its signature. Per-argument
documentation lives here as ``Field(description=...)`` instead of an
``Args:`` docstring section, because clients truncate tool descriptions
(Claude Code keeps 2048 characters) but pass the schema through whole.

Shapes the model must get right (``sort``, ``aggregate``,
``include_inlines``) are ``TypedDict``s with ``extra="forbid"``, so the
schema advertises the exact keys and FastMCP rejects a malformed call
before the tool runs. The tools themselves keep only the checks that need
the admin (unknown columns, numeric fields, relation columns).

The REST transport calls the tool methods directly, so it validates through
the same argument model with :func:`validate_tool_arguments`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, with_config
from typing_extensions import NotRequired, TypedDict

from django_smartbase_admin.actions.admin_action_list import LIST_AGGREGATE_FUNCTIONS

AggregateFn = Literal[tuple(LIST_AGGREGATE_FUNCTIONS)]


@with_config(ConfigDict(extra="forbid"))
class SortSpec(TypedDict):
    field: Annotated[
        str, Field(description="Column name from list_admins fields[].name.")
    ]
    dir: Literal["asc", "desc"]


@with_config(ConfigDict(extra="forbid"))
class AggregateSpec(TypedDict):
    fn: AggregateFn
    field: NotRequired[
        Annotated[
            str,
            Field(
                description="Declared column. sum/avg/min/max need a numeric one; "
                "omit it with count for a row count."
            ),
        ]
    ]


@with_config(ConfigDict(extra="forbid"))
class InlineSpec(TypedDict):
    inline_name: Annotated[
        str, Field(description="list_admins admin_views[].inlines[].inline_name.")
    ]
    fields: Annotated[
        list[str],
        Field(min_length=1, description="Fields from that inline's list_admins entry."),
    ]


ViewId = Annotated[str, Field(description="Admin handle from list_admins.")]
ObjectId = Annotated[str, Field(description="Target row id, as a string.")]
ObjectIds = Annotated[
    list[str | int],
    Field(min_length=1, description="Row ids to act on, as returned by list_rows."),
]
Confirmed = Annotated[
    bool,
    Field(
        description="Set true on the second call, after a needs_confirmation response."
    ),
]
ActionComponentValues = Annotated[
    dict | None,
    Field(
        description="Named forms and formset rows, keyed like "
        "fetch_action_form.components. Omit for method actions."
    ),
]
Modifier = Annotated[
    str | None,
    Field(description="Action URL modifier. Defaults to the action's own."),
]
FilterData = Annotated[
    dict | None,
    Field(
        description="{column name: value}. Keys are list_admins fields[].name "
        "(keys from fetch_filter_preset are accepted as-is). Copy each value's "
        "shape from list_admins widget_shapes for that filter's widget. "
        "Autocomplete filters take ids from the autocomplete tool, not names. "
        "Unknown keys are rejected."
    ),
]
FullTextSearch = Annotated[
    str | None,
    Field(description="Free text over the admin's search_fields. No-op when empty."),
]
Page = Annotated[int, Field(description="1-indexed page number.")]
DetailFields = Annotated[
    list[str] | None,
    Field(
        description="Subset of list_admins detail_fields. Omit for all. "
        "Unknown names raise LookupError."
    ),
]


_ARG_MODELS: dict[Any, Any] = {}


def validate_tool_arguments(method, arguments: dict) -> dict:
    """Validate ``arguments`` against the FastMCP argument model of ``method``.

    Returns keyword arguments ready for ``method(**kwargs)``, with defaults
    filled in. Raises ``pydantic.ValidationError`` (a ``ValueError``) on a
    malformed call and ``TypeError`` on an unknown argument, as a direct
    Python call would.
    """
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata

    key = getattr(method, "__func__", method)
    meta = _ARG_MODELS.get(key)
    if meta is None:
        meta = _ARG_MODELS[key] = func_metadata(method)
    model = meta.arg_model
    known = {info.alias or name for name, info in model.model_fields.items()}
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise TypeError(f"Unknown argument(s) {unknown}; accepted: {sorted(known)}.")
    return model.model_validate(meta.pre_parse_json(arguments)).model_dump_one_level()
