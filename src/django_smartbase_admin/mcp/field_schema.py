"""Per-field schema helpers shared by detail and action-form discovery.

Both ``service.py`` (change-form / detail page) and ``actions.py``
(modal action forms) need to convert a ``(field, widget)`` pair into
the small bits of metadata the agent uses — the dispatch handle for
autocomplete lookups, the target model for relational fields, and the
enumerable choices for flat-choice fields.

The walking of forms differs between the two contexts (``AdminForm``
fieldsets vs. plain ``form.fields``), but these per-field bits do not.
"""

from __future__ import annotations

from django.forms import ModelChoiceField, ModelMultipleChoiceField
from django.forms.forms import BaseForm

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


def get_mcp_schema_from_form(form: BaseForm) -> dict:
    """Convert an unbound Django form into the MCP action-input schema.

    The field representation intentionally matches ``fetch_action_form`` so
    callers see one form contract whether the form comes from a modal action
    or an ``@sbadmin_action(mcp_schema=...)`` method.
    """
    fields: dict[str, dict] = {}
    for name, field in form.fields.items():
        initial = (form.initial or {}).get(name)
        if initial is None:
            raw = field.initial
            initial = raw() if callable(raw) else raw
        fields[name] = field_info(field, initial, label=str(field.label or name))
    return {"kind": "form", "fields": fields}
