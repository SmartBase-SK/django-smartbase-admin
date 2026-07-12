"""POST-encoding helpers shared by detail-write and modal-action paths.

The detail change-form path (``service.py``) and the modal action
submission path (``actions.py``) both need to convert MCP-typed Python
values into the per-widget POST shape that Django's ``_changeform_view``
and ``FormView.post`` read back. Both paths also accept the
``{"value", "label"}`` envelope returned by the read-side discovery
tools so agents can echo a fetched payload back unchanged.

Public entry points
-------------------
unwrap_envelope(value)
    Strip the ``{"value", "label"}`` wrapper, recursing into lists.

write_widget_input(qd, key, widget, value)
    Adapt one ``(widget, value)`` pair into ``qd`` in whatever shape the
    widget reads back. Handles ``FileInput`` (omit key — preserve current
    file), ``MultiWidget`` (``decompress`` into sub-keys), multi-select,
    SBAdmin autocomplete, and plain widgets.

encode_form_components(components, component_values)
    Encode named form patches and formset row operations through the same
    widget-aware path for admin writes, modal actions, and method actions.
"""

from __future__ import annotations

from copy import copy

from django.forms.formsets import BaseFormSet
from django.forms.forms import BaseForm
from django.forms.models import BaseModelFormSet
from django.forms.widgets import (
    CheckboxSelectMultiple,
    ClearableFileInput,
    FileInput,
    MultiWidget,
    SelectMultiple,
    SplitDateTimeWidget,
)
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_smartbase_admin.engine.filter_widgets import AutocompleteParseMixin


def unwrap_envelope(value):
    """Accept ``{"value", "label"}`` (or list of) from ``fetch_detail`` /
    ``fetch_action_form``. Lets agents echo a fetched payload back
    unchanged. Unrecognised shapes pass through untouched so writes from
    other sources still work.
    """
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    if isinstance(value, list):
        return [
            v["value"] if isinstance(v, dict) and "value" in v else v for v in value
        ]
    return value


def write_widget_input(qd: QueryDict, key: str, widget, value) -> None:
    """Adapt MCP-typed Python ``value`` to the per-widget ``data`` shape.

    Mirrors ``widget.value_from_datadict`` one-to-one: writes ``value``
    into ``qd`` in whatever shape this widget reads back when the view
    runs, so the field's ``to_python`` receives the right thing. Plain
    widgets pass through; widgets with a custom POST contract (file,
    multiselect, ``MultiWidget``, autocomplete) get a shape-specific
    write.

    No string encoding — ``QueryDict`` stores native Python unchanged
    (``bytes_to_text`` only touches bytes) and the common
    ``Field.to_python`` implementations accept native ``bool``, ``int``,
    ``date``, etc.
    """
    value = unwrap_envelope(value)

    if isinstance(widget, (FileInput, ClearableFileInput)):
        # Omit the key — ``ClearableFileInput`` treats absence as "no
        # upload, keep current value", same as a browser submitting an
        # empty file input.
        return

    if isinstance(widget, MultiWidget):
        # MultiWidget renders multiple inputs and reads them back as a
        # list of per-subwidget strings via ``value_from_datadict``. The
        # form field's ``compress()`` is what merges them — the widget
        # itself never parses a single value into parts. We mirror what
        # the browser POSTs: per-subwidget string keys.
        #
        # Shapes supported:
        #   * pre-split list of correct length — used as-is
        #   * ``SplitDateTimeWidget``: ISO string (split on space-or-``T``)
        #     OR a ``datetime`` instance (split into date+time)
        if value is None:
            subvalues = [None] * len(widget.widgets)
        elif isinstance(value, (list, tuple)) and len(value) == len(widget.widgets):
            subvalues = list(value)
        elif isinstance(widget, SplitDateTimeWidget):
            if isinstance(value, str):
                parsed = parse_datetime(value)
                if parsed is not None:
                    # Accept tz-aware ISO (``Z`` / offset) on the way in;
                    # localize so the date/time subwidgets get the wall-clock
                    # value they expect (no offset suffix). Django re-awares
                    # it via from_current_timezone on save.
                    if timezone.is_aware(parsed):
                        parsed = timezone.localtime(parsed)
                    subvalues = [parsed.date(), parsed.time()]
                else:
                    parts = value.replace("T", " ", 1).split(" ", 1)
                    subvalues = parts if len(parts) == 2 else [parts[0], ""]
            elif hasattr(value, "date") and hasattr(value, "time"):
                # datetime instance — flow used by form.initial values
                # in ``encode_initial_form_values``.
                local = timezone.localtime(value) if timezone.is_aware(value) else value
                subvalues = [local.date(), local.time()]
            else:
                raise TypeError(
                    f"Unsupported value shape {type(value).__name__!r} for "
                    f"SplitDateTimeWidget; pass an ISO string, datetime, "
                    f"or [date, time] list."
                )
        else:
            # Any other MultiWidget (e.g. a datetime-range): fall back to the
            # widget's own decompress to split a compressed value (a Range,
            # tuple, …) into per-subwidget parts — the inverse of the read
            # side's mcp_read_value, so a restated form.initial value works.
            try:
                decompressed = list(widget.decompress(value))
            except Exception:
                decompressed = None
            if decompressed is not None and len(decompressed) == len(widget.widgets):
                subvalues = decompressed
            else:
                raise TypeError(
                    f"Unsupported value shape {type(value).__name__!r} for "
                    f"{widget.__class__.__name__}; pass a {len(widget.widgets)}-item "
                    f"list of per-subwidget values."
                )
        for subname, subwidget, subvalue in zip(
            widget.widgets_names, widget.widgets, subvalues
        ):
            write_widget_input(qd, key + subname, subwidget, subvalue)
        return

    if isinstance(widget, (SelectMultiple, CheckboxSelectMultiple)):
        qd.setlist(key, list(value) if value not in (None, "") else [])
        return

    if isinstance(widget, AutocompleteParseMixin):
        # Always a list — single-select widgets unwrap with
        # ``next(iter(...), None)`` on the read side, which needs an
        # iterable.
        if value in (None, ""):
            qd[key] = []
        elif isinstance(value, (list, tuple, set)):
            qd[key] = list(value)
        else:
            qd[key] = [value]
        return

    qd[key] = value


def form_errors_dict(form) -> dict:
    """Stringify ``form.errors`` into ``{field: [message, ...]}``.

    Non-field errors (cross-field validation, view-raised errors via
    ``form.add_error(None, ...)``) appear under the key ``"non_field"``
    instead of Django's internal ``__all__`` sentinel — the renamed key
    is agent-friendly and explicit about what it represents.
    """
    from django.core.exceptions import NON_FIELD_ERRORS

    return {
        ("non_field" if name == NON_FIELD_ERRORS else name): [str(e) for e in errors]
        for name, errors in form.errors.items()
    }


def formset_errors_dict(formset: BaseFormSet) -> dict:
    """Return row and formset-wide validation errors in MCP shape."""
    rows = [
        {"index": index, "errors": form_errors_dict(form)}
        for index, form in enumerate(formset.forms)
        if form.errors
    ]
    return {
        "rows": rows,
        "non_form": [str(error) for error in formset.non_form_errors()],
    }


def form_component_errors(
    components: dict[str, BaseForm | BaseFormSet],
) -> dict[str, dict]:
    """Collect errors from named bound forms and formsets."""
    errors = {}
    for name, component in components.items():
        if isinstance(component, BaseFormSet):
            component_errors = formset_errors_dict(component)
            if component_errors["rows"] or component_errors["non_form"]:
                errors[name] = component_errors
        else:
            component_errors = form_errors_dict(component)
            if component_errors:
                errors[name] = component_errors
    return errors


def bind_form_components(
    components: dict[str, BaseForm | BaseFormSet], data: QueryDict
) -> dict[str, BaseForm | BaseFormSet]:
    """Return bound copies of components for validation without side effects."""
    bound_components = {}
    for name, component in components.items():
        bound = copy(component)
        bound.data = data
        bound.files = MultiValueDict()
        bound.is_bound = True
        if isinstance(bound, BaseFormSet):
            for cached in ("forms", "management_form"):
                bound.__dict__.pop(cached, None)
            bound._errors = None
            bound._non_form_errors = None
        else:
            bound._errors = None
            bound._bound_fields_cache = {}
        bound.full_clean()
        bound_components[name] = bound
    return bound_components


def reject_non_writable_overrides(
    overrides: dict,
    writable: set[str],
    scope: str,
    *,
    skip: frozenset[str] = frozenset(),
) -> None:
    """Reject unknown and readonly field names before Django can ignore them."""
    invalid = sorted(
        key for key in overrides if key not in writable and key not in skip
    )
    if invalid:
        raise LookupError(f"Cannot set {scope} {invalid}; writable: {sorted(writable)}")


def encode_initial_form_values(
    form, qd: QueryDict, overrides: dict, *, prefix: str | None = None
) -> None:
    """Encode a form's initial state with caller-provided overrides layered on."""
    reject_non_writable_overrides(
        overrides,
        set(form.fields),
        "form fields",
    )
    prefix = form.prefix if prefix is None else prefix
    for name, field in form.fields.items():
        full_name = f"{prefix}-{name}" if prefix else name
        value = overrides[name] if name in overrides else form.initial.get(name)
        write_widget_input(qd, full_name, field.widget, value)


def _write_formset_management(formset: BaseFormSet, qd: QueryDict, total: int) -> None:
    prefix = formset.prefix
    initial = len(formset.initial_forms)
    qd[f"{prefix}-TOTAL_FORMS"] = str(total)
    qd[f"{prefix}-INITIAL_FORMS"] = str(initial)
    qd[f"{prefix}-MIN_NUM_FORMS"] = str(formset.min_num)
    qd[f"{prefix}-MAX_NUM_FORMS"] = str(formset.max_num)


def encode_formset_rows(
    formset: BaseFormSet,
    qd: QueryDict,
    rows: list[dict],
    *,
    scope: str = "formset fields",
) -> None:
    """Encode a complete row list for an action-owned Django formset.

    Prefixes and management-form values are derived from the live formset.
    Initial forms are positional and must be included in ``rows``; extra rows
    are encoded against ``empty_form``. ``_delete`` and ``_order`` are the
    transport-friendly aliases for Django's generated control fields.
    """
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("formset values must be a list of field dictionaries.")

    initial_count = len(formset.initial_forms)
    if len(rows) < initial_count:
        raise ValueError(
            f"Formset {formset.prefix!r} has {initial_count} initial rows; "
            f"received only {len(rows)} rows."
        )

    _write_formset_management(formset, qd, len(rows))
    special = frozenset({"_delete", "_order"})
    row_field_names = getattr(formset, "mcp_field_names", None)
    if row_field_names is None:
        row_field_names = getattr(formset, "multiple_field_names", None)
    for index, row in enumerate(rows):
        if "_delete" in row and not formset.can_delete:
            raise ValueError(f"Formset {formset.prefix!r} does not allow deletion.")
        if "_order" in row and not formset.can_order:
            raise ValueError(f"Formset {formset.prefix!r} does not allow ordering.")
        form = (
            formset.forms[index] if index < len(formset.forms) else formset.empty_form
        )
        writable = set(form.fields) - {"DELETE", "ORDER"}
        if row_field_names is not None:
            writable &= set(row_field_names)
        reject_non_writable_overrides(row, writable, scope, skip=special)
        for name, field in form.fields.items():
            if name not in writable:
                continue
            if name in row:
                value = row[name]
            elif index < initial_count:
                value = form.initial.get(name)
            else:
                continue
            write_widget_input(
                qd,
                f"{formset.prefix}-{index}-{name}",
                field.widget,
                value,
            )
        if row.get("_delete") and formset.can_delete:
            qd[f"{formset.prefix}-{index}-DELETE"] = "on"
        if "_order" in row and formset.can_order:
            qd[f"{formset.prefix}-{index}-ORDER"] = row["_order"]


def _is_blank_form_value(value) -> bool:
    if value in (None, "", [], {}):
        return True
    if isinstance(value, dict) and "value" in value:
        return value["value"] in (None, "")
    return False


def encode_inline_formset_operations(
    formset: BaseFormSet,
    qd: QueryDict,
    operations: list[dict],
    *,
    scope: str,
) -> None:
    """Encode create/update/delete operations for a model-admin inline."""
    sample_form = (
        formset.initial_forms[0] if formset.initial_forms else formset.empty_form
    )
    writable = set(sample_form.fields)
    transport_fields = frozenset({"id", "_delete", "_order"})
    seen_ids = set()
    for operation in operations:
        if "_delete" in operation and not formset.can_delete:
            raise ValueError(f"Formset {formset.prefix!r} does not allow deletion.")
        if "_order" in operation and not formset.can_order:
            raise ValueError(f"Formset {formset.prefix!r} does not allow ordering.")
        if "id" in operation:
            if operation["id"] in seen_ids:
                raise ValueError(
                    f"Formset {formset.prefix!r} received duplicate row id "
                    f"{operation['id']!r}."
                )
            seen_ids.add(operation["id"])
        reject_non_writable_overrides(
            operation,
            writable,
            scope,
            skip=transport_fields,
        )

    operations_by_id = {
        operation["id"]: operation for operation in operations if "id" in operation
    }
    new_operations = [operation for operation in operations if "id" not in operation]
    for operation in new_operations:
        meaningful = {
            key: value
            for key, value in operation.items()
            if key not in transport_fields
        }
        if not meaningful or all(
            _is_blank_form_value(value) for value in meaningful.values()
        ):
            raise ValueError(
                f"{scope} new row {operation!r} has no field values; "
                "provide the row's required fields, or omit it."
            )

    initial_forms = list(formset.initial_forms)
    _write_formset_management(formset, qd, len(initial_forms) + len(new_operations))

    for index, form in enumerate(initial_forms):
        pk = form.instance.pk
        operation = operations_by_id.pop(pk, None)
        deleted = bool(operation and operation.get("_delete"))
        for name, field in form.fields.items():
            if name == "id":
                value = pk
            elif operation and not deleted and name in operation:
                value = operation[name]
            else:
                value = form.initial.get(name)
            write_widget_input(
                qd,
                f"{formset.prefix}-{index}-{name}",
                field.widget,
                value,
            )
        if deleted:
            qd[f"{formset.prefix}-{index}-DELETE"] = "on"
        if operation and "_order" in operation:
            qd[f"{formset.prefix}-{index}-ORDER"] = operation["_order"]

    if operations_by_id:
        raise LookupError(
            f"Inline rows {sorted(operations_by_id)} not found on "
            f"{formset.prefix!r}; use ids from fetch_detail."
        )

    empty_form = formset.empty_form
    for offset, operation in enumerate(new_operations):
        index = len(initial_forms) + offset
        for name, field in empty_form.fields.items():
            if name == "id":
                continue
            write_widget_input(
                qd,
                f"{formset.prefix}-{index}-{name}",
                field.widget,
                operation.get(name),
            )
        if "_order" in operation:
            qd[f"{formset.prefix}-{index}-ORDER"] = operation["_order"]


def normalize_querydict_values(qd: QueryDict) -> QueryDict:
    """Normalize scalar values to the strings a browser would submit."""
    for name in list(qd):
        qd.setlist(
            name,
            [
                (
                    value
                    if isinstance(value, (list, tuple, dict))
                    else "" if value is None else str(value)
                )
                for value in qd.getlist(name)
            ],
        )
    return qd


def encode_form_components(
    components: dict[str, BaseForm | BaseFormSet],
    component_values: dict | None,
    *,
    allow_existing_rows: bool = True,
) -> QueryDict:
    """Encode named form patches and formset row operations into one POST."""
    from django_smartbase_admin.mcp.field_schema import validate_form_components

    components = validate_form_components(components)
    values = component_values or {}
    if not isinstance(values, dict):
        raise TypeError("component_values must be a dictionary.")
    unknown = sorted(set(values) - set(components))
    if unknown:
        raise LookupError(
            f"Unknown form components: {unknown}; available: {sorted(components)}."
        )

    prefixes = [component.prefix or "" for component in components.values()]
    duplicates = sorted({prefix for prefix in prefixes if prefixes.count(prefix) > 1})
    if duplicates:
        raise ValueError(
            "Form component prefixes must be unique; duplicated prefixes: "
            f"{duplicates}."
        )

    qd = QueryDict(mutable=True)
    for name, component in components.items():
        supplied = values.get(name)
        if isinstance(component, BaseFormSet):
            rows = supplied
            if rows is None:
                rows = (
                    []
                    if isinstance(component, BaseModelFormSet)
                    else [{} for _form in component.initial_forms]
                )
            if not isinstance(rows, list):
                raise TypeError(f"Formset component {name!r} must be a list of rows.")
            if not allow_existing_rows and any(
                "id" in row or row.get("_delete") for row in rows
            ):
                raise LookupError(
                    f"Formset component {name!r} cannot update or delete rows "
                    "while creating an object."
                )
            if isinstance(component, BaseModelFormSet):
                encode_inline_formset_operations(
                    component,
                    qd,
                    rows,
                    scope=f"formset component {name!r} fields",
                )
            else:
                encode_formset_rows(
                    component,
                    qd,
                    rows,
                    scope=f"formset component {name!r} fields",
                )
            continue

        supplied = supplied or {}
        if not isinstance(supplied, dict):
            raise TypeError(f"Form component {name!r} must be a field dictionary.")
        encode_initial_form_values(component, qd, supplied)

    return normalize_querydict_values(qd)
