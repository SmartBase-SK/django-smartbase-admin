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

encode_field_values(form, field_values)
    High-level helper for modal action submission: builds a fresh
    ``QueryDict`` keyed by ``form.fields`` widgets, rejecting unknown
    field names up-front so agents get a clear ``LookupError`` instead
    of silently-dropped values.
"""

from __future__ import annotations

from django.forms.widgets import (
    CheckboxSelectMultiple,
    ClearableFileInput,
    FileInput,
    MultiWidget,
    SelectMultiple,
    SplitDateTimeWidget,
)
from django.http import QueryDict

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
                parts = value.replace("T", " ", 1).split(" ", 1)
                subvalues = parts if len(parts) == 2 else [parts[0], ""]
            elif hasattr(value, "date") and hasattr(value, "time"):
                # datetime instance — flow used by form.initial values
                # in ``_encode_form_native``.
                subvalues = [value.date(), value.time()]
            else:
                raise TypeError(
                    f"Unsupported value shape {type(value).__name__!r} for "
                    f"SplitDateTimeWidget; pass an ISO string, datetime, "
                    f"or [date, time] list."
                )
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


def get_form_from_response(response, key: str):
    """Return the form attached to a ``TemplateResponse``'s context.

    ``key`` is ``"form"`` for ``FormView``-style responses or
    ``"adminform"`` for Django admin change-form responses (in which
    case the ``AdminForm`` wrapper's ``.form`` is unwrapped). Returns
    ``None`` when the response isn't a ``TemplateResponse`` or no form
    is found.

    Used in failure paths to surface errors that the dispatched view
    attached to the form (including non-field errors added
    programmatically by ``process_form_valid``).
    """
    ctx = getattr(response, "context_data", None)
    if not ctx or key not in ctx:
        return None
    obj = ctx[key]
    return getattr(obj, "form", obj)


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


def encode_field_values(form, field_values: dict) -> QueryDict:
    """Encode a flat ``{name: value}`` dict into a POST ``QueryDict`` using
    each field's widget for correct shape.

    Unknown field names raise ``LookupError`` so agents see a clear
    failure rather than silently-dropped values. Use for modal action
    submission where the agent supplies a discrete set of field values
    against a known form schema.
    """
    qd = QueryDict(mutable=True)
    writable = set(form.fields)
    unknown = sorted(k for k in field_values if k not in writable)
    if unknown:
        raise LookupError(f"Unknown fields: {unknown}; available: {sorted(writable)}")
    for name, value in field_values.items():
        write_widget_input(qd, name, form.fields[name].widget, value)
    return qd
