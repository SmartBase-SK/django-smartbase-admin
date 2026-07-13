"""Serialize Django fields, forms, and formsets for MCP.

All writable MCP surfaces use named ``BaseForm`` or ``BaseFormSet`` components.
Discovery serializes them to a shared wire format::

    {
        "components": {
            "main": {
                "type": "form",
                "fields": {
                    "name": {
                        "value": "Article",
                        "value_available": True,
                        "write_only": False,
                        "readonly": False,
                        "required": True,
                        "widget": "TextInput",
                    },
                },
            },
            "CommentInline": {
                "type": "formset",
                "fields": {"text": {...}},
                "rows": [{"id": 7, "fields": {"text": {...}}}],
                "can_delete": True,
                "can_order": False,
            },
        },
    }

``value_available`` distinguishes a disclosed null from a redacted value.
Writable password fields and fields marked ``mcp_write_only`` report
``write_only=True`` without exposing their current value.

Invocation uses the same component names::

    {
        "component_values": {
            "main": {"name": "Updated article"},
            "CommentInline": [
                {"id": 7, "text": "Updated comment"},
                {"id": 8, "_delete": True},
                {"text": "New comment"},
            ],
        },
    }

For model formsets, ``id`` updates an existing row, ``_delete`` deletes it,
and a row without ``id`` creates one. Omitted rows remain unchanged. Plain
formsets use positional rows. Component names are public identifiers; Django
prefixes and management-form fields remain internal encoding details.

Validation errors follow the same component hierarchy and distinguish global,
form-wide, formset-wide, row, and field errors. Unknown components, fields, or
row ids are tool errors rather than validation errors.

These helpers only validate and serialize the component contract. Admin
presentation data is enriched separately, while saving and permission checks
remain in the normal Django admin, modal, and action paths.
"""

from __future__ import annotations

from django.forms import ModelChoiceField, ModelMultipleChoiceField, PasswordInput
from django.forms.forms import BaseForm
from django.forms.formsets import BaseFormSet

from django_smartbase_admin.engine.filter_widgets import AutocompleteParseMixin


def widget_id_for(widget) -> str | None:
    """Return the SBAdmin autocomplete ``widget_id``, or ``None``.

    Detects autocomplete-backed widgets by the mixin that actually
    provides ``get_id()`` — broader than ``AutocompleteFilterWidget``,
    which is only one of its subclasses.
    """
    if not isinstance(widget, AutocompleteParseMixin):
        return None
    try:
        return widget.get_id()
    except Exception:
        return None


def target_model_for(field) -> str | None:
    """Return ``"<app>.<Model>"`` for relational form fields, else ``None``.

    Use with the ``autocomplete`` MCP tool to resolve a name to a pk.
    """
    if isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
        opts = field.queryset.model._meta
        return f"{opts.app_label}.{opts.object_name}"
    return None


def choices_for(field) -> list[dict] | None:
    """Return ``[{value, label}, ...]`` for flat-choice fields, else ``None``.

    Relational fields are excluded — their querysets may be large and
    should be resolved via the ``autocomplete`` tool, not enumerated
    here at discovery time.
    """
    if isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
        return None
    choices = getattr(field, "choices", None)
    if not choices:
        return None
    try:
        return [{"value": v, "label": str(lbl)} for v, lbl in choices if v != ""]
    except Exception:
        return None


def field_info(field, value, *, readonly=False, label=None) -> dict:
    """Per-field schema dict shared by detail and modal form discovery.

    For readonly cells pass ``field=None`` (or any field with
    ``readonly=True``); disabled Django fields are also treated as readonly.
    Password inputs and fields/widgets declaring ``mcp_write_only=True`` are
    writable without disclosing their current value. A field/widget can set
    ``mcp_value_available=False`` to suppress a sensitive display value.

    Always present: ``value``, ``value_available``, ``write_only``,
    ``required``, ``widget``, ``readonly``.
    Added when applicable: ``widget_id`` (autocomplete-backed widget),
    ``target_model`` (relational field), ``choices`` (flat-choice field),
    ``label`` (when passed explicitly — modal forms ship one, detail
    fields rely on admin-side labels).
    """
    widget = field.widget if field is not None else None
    readonly = bool(readonly or field is None or getattr(field, "disabled", False))
    write_only = bool(
        not readonly
        and field is not None
        and (
            getattr(field, "mcp_write_only", False)
            or getattr(widget, "mcp_write_only", False)
            or isinstance(widget, PasswordInput)
        )
    )
    value_available = bool(
        not write_only
        and getattr(
            field,
            "mcp_value_available",
            getattr(widget, "mcp_value_available", True),
        )
    )
    serialized_value = value if value_available else None

    if readonly:
        info: dict = {
            "value": serialized_value,
            "value_available": value_available,
            "write_only": False,
            "required": False,
            "widget": None,
            "readonly": True,
        }
    else:
        info = {
            "value": serialized_value,
            "value_available": value_available,
            "write_only": write_only,
            "required": bool(field.required),
            "widget": widget.__class__.__name__,
            "readonly": False,
        }
        widget_id = widget_id_for(widget)
        if widget_id is not None:
            info["widget_id"] = widget_id
        target_model = target_model_for(field)
        if target_model is not None:
            info["target_model"] = target_model
        choices = choices_for(field)
        if choices is not None:
            info["choices"] = choices

    if label is not None:
        info["label"] = label
    return info


def validate_form_components(components) -> dict[str, BaseForm | BaseFormSet]:
    """Validate and return one named form-component mapping."""
    if not isinstance(components, dict):
        raise TypeError("Form components must be a dictionary.")
    invalid = {
        name: type(component).__name__
        for name, component in components.items()
        if not isinstance(name, str)
        or not name
        or not isinstance(component, (BaseForm, BaseFormSet))
    }
    if invalid:
        raise TypeError(
            "Form components must map non-empty string names to Django forms "
            f"or formsets; invalid: {invalid}."
        )
    return components


def serialize_form_component(
    form: BaseForm, *, field_names: set[str] | None = None
) -> dict:
    """Serialize one Django form as a writable MCP component."""
    fields: dict[str, dict] = {}
    for name, field in form.fields.items():
        if field_names is not None and name not in field_names:
            continue
        initial = (form.initial or {}).get(name)
        if initial is None:
            raw = field.initial
            initial = raw() if callable(raw) else raw
        fields[name] = field_info(field, initial, label=str(field.label or name))
    return {"type": "form", "fields": fields}


def serialize_formset_component(
    formset: BaseFormSet, *, field_names: set[str] | None = None
) -> dict:
    """Serialize a formset's row schema, existing rows, and controls."""
    excluded_controls = {"DELETE", "ORDER"}
    if field_names is None:
        field_names = getattr(formset, "mcp_field_names", None)
    if field_names is None:
        # Compound bulk forms commonly expose fixed fields separately and
        # identify the fields repeated per row with this attribute.
        field_names = getattr(formset, "multiple_field_names", None)
    selected = (
        set(formset.empty_form.fields) - excluded_controls
        if field_names is None
        else set(field_names) - excluded_controls
    )
    schema = serialize_form_component(formset.empty_form, field_names=selected)
    rows = []
    for index, form in enumerate(formset.initial_forms):
        row = {"fields": serialize_form_component(form, field_names=selected)["fields"]}
        instance = getattr(form, "instance", None)
        object_id = getattr(instance, "pk", None)
        if object_id is not None:
            row["id"] = object_id
        else:
            row["index"] = index
        rows.append(row)
    return {
        "type": "formset",
        "fields": schema["fields"],
        "rows": rows,
        "min_num": formset.min_num,
        "max_num": formset.max_num,
        "can_delete": bool(formset.can_delete),
        "can_order": bool(formset.can_order),
    }


def serialize_form_components(
    components: dict[str, BaseForm | BaseFormSet],
) -> dict[str, dict]:
    """Serialize named forms and formsets through one wire contract."""
    serialized = {}
    for name, component in validate_form_components(components).items():
        if isinstance(component, BaseFormSet):
            serialized[name] = serialize_formset_component(component)
        else:
            serialized[name] = serialize_form_component(component)
    return serialized
