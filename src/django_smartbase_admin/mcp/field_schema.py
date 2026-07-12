"""Form-component and per-field schema contracts used by MCP.

Both ``service.py`` (change-form / detail page) and ``actions.py``
(modal action forms) need to convert a ``(field, widget)`` pair into
the small bits of metadata the agent uses — the dispatch handle for
autocomplete lookups, the target model for relational fields, and the
enumerable choices for flat-choice fields.

The walking of forms differs between the two contexts (``AdminForm``
fieldsets vs. plain ``form.fields``), but these per-field bits do not.

Form-component contract
=======================

All writable MCP surfaces normalize to one named component mapping::

    get_form_components() -> dict[str, BaseForm | BaseFormSet]

``BaseForm`` and ``BaseFormSet`` are the internal Python contract.  The MCP
wire representation adds the component type and serialized field metadata::

    {
        "id": 42,
        "components": {
            "main": {
                "type": "form",
                "fields": {
                    "name": {
                        "value": "Article",
                        "readonly": False,
                        "required": True,
                        "widget": "TextInput",
                    },
                    "created_by_display": {
                        "value": "John",
                        "readonly": True,
                        "required": False,
                        "widget": None,
                    },
                },
            },
            "CommentInline": {
                "type": "formset",
                "fields": {
                    "text": {
                        "value": None,
                        "readonly": False,
                        "required": True,
                        "widget": "Textarea",
                    },
                },
                "rows": [
                    {
                        "id": 7,
                        "fields": {
                            "text": {
                                "value": "Existing comment",
                                "readonly": False,
                                "required": True,
                                "widget": "Textarea",
                            },
                        },
                    },
                ],
                "min_num": 0,
                "max_num": 1000,
                "can_delete": True,
                "can_order": False,
                "truncated": False,
            },
        },
        "widgets": [],
    }

Invocation uses the same component names.  A form receives a field mapping;
a formset receives a list of row mappings::

    {
        "component_values": {
            "main": {"name": "Article"},
            "CommentInline": [
                {"id": 7, "text": "Updated comment"},
                {"id": 8, "_delete": True},
                {"text": "New comment"},
            ],
        },
    }

For model-backed formsets, a row with ``id`` updates that existing row, a
row with ``id`` and ``_delete`` deletes it when deletion is allowed, and a
row without ``id`` creates a new row.  Existing rows omitted from
``component_values`` remain unchanged.  Plain non-model formsets without a
stable row id use their Django positional row order instead.

Multiple forms must use distinct prefixes so their encoded POST fields cannot
collide.  Formset components retain their Django prefixes and management-form
fields.  Component names are stable public handles; prefixes remain an
internal encoding concern.

Admin wrappers and enrichment
-----------------------------

A normal admin page is adapted from the GET response context::

    {
        "main": context["adminform"].form,
        **{
            type(inline.opts).__name__: inline.formset
            for inline in context["inline_admin_formsets"]
        },
    }

The raw forms are sufficient for writable fields, widget-aware POST encoding,
validation, formset management fields, and autocomplete registration.  They
do not contain admin-only presentation state.  The admin adapter must continue
to enrich the serialized components from ``AdminForm`` and
``InlineAdminForm`` with readonly fields, display methods, existing row ids,
pagination/truncation, sanitized display values, and detail widgets.
Fieldset grouping and inline permissions are not currently explicit wire
metadata; permissions remain enforced by the normal admin request pipeline.

The component layer never saves objects itself. Admin writes still dispatch
through ``ModelAdmin._changeform_view`` so ``save_model``, ``save_formset``,
``save_related``, transactions, permissions, messages, and redirects retain
their Django behavior.  Modal actions still dispatch through their view's
``post`` method, and method actions still use ``delegate_to_action``.

Shared implementation and call graphs
-------------------------------------

All three paths reuse the same component operations::

    provider / admin-context adapter
      -> validate_form_components()
      -> serialize_form_components()      # discovery
      -> encode_form_components()         # invocation
      -> form_component_errors()          # validation response

Only component acquisition, admin presentation enrichment, and final dispatch
are path-specific.

Normal add/change view discovery::

    fetch_add_form / fetch_detail
      -> ModelAdmin._changeform_view(GET)
      -> adapt adminform + inline_admin_formsets to named components
      -> serialize_form_components()
      -> enrich from AdminForm / InlineAdminForm wrappers
      -> {id?, components, widgets?}

Normal add/change view invocation::

    create_object / update_detail
      -> ModelAdmin._changeform_view(GET)
      -> adapt named components
      -> encode_form_components(component_values)
      -> ModelAdmin._changeform_view(POST)
      -> success: refetch components
         failure: extract component errors from the bound response context

Modal action discovery and invocation::

    fetch_action_form
      -> resolve and set up ActionModalView
      -> action_view.get_form_components()
      -> serialize_form_components()

    invoke_*_action
      -> action_view.get_form_components()
      -> encode_form_components(component_values)
      -> action_view.post()
      -> normalize success or bound component errors

Method ``@sbadmin_action`` discovery and invocation use the same provider
result instead of a separate form/schema contract::

    @sbadmin_action(mcp_components="get_recalculate_form_components")
    def action_recalculate(self, request, modifier, object_id=None):
        ...

    def get_recalculate_form_components(self, request):
        return {"main": RecalculateForm()}

Its call graph is::

    discovery
      -> resolve @sbadmin_action mcp_components provider
      -> provider(request) returns named BaseForm/BaseFormSet components
      -> serialize_form_components()

    invocation
      -> resolve the same provider
      -> encode_form_components(component_values)
      -> bind_form_components() + form_component_errors()
      -> delegate_to_action(request, modifier, object_id)
"""

from __future__ import annotations

from django.forms import ModelChoiceField, ModelMultipleChoiceField
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
    ``readonly=True``); the result carries ``widget=None`` and
    ``required=False`` per the readonly contract used by ``fetch_detail``.

    Always present: ``value``, ``required``, ``widget``, ``readonly``.
    Added when applicable: ``widget_id`` (autocomplete-backed widget),
    ``target_model`` (relational field), ``choices`` (flat-choice field),
    ``label`` (when passed explicitly — modal forms ship one, detail
    fields rely on admin-side labels).
    """
    if readonly or field is None:
        info: dict = {
            "value": value,
            "required": False,
            "widget": None,
            "readonly": True,
        }
    else:
        widget = field.widget
        info = {
            "value": value,
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
