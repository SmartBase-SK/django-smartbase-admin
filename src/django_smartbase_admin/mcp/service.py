"""Detail-page MCP service — read + write through ``ModelAdmin._changeform_view``.

The MCP tool surface (``fetch_detail`` / ``update_detail``) is implemented
here, off the admin classes themselves, so :class:`SBAdmin` stays focused
on the regular UI flow and the mock-request plumbing lives in one place.
Public entry points are classmethods on :class:`SBAdminMCPDetailService`; they
take the resolved admin in and do not assume any extra mixin on it.

Both reads and writes run the *same* ``_changeform_view`` against a mock
request, so fetch and update share form construction, fieldsets, inline
prefixes, permission gates, and the readonly/required schema.
"""

from __future__ import annotations

import logging

from django.contrib.admin import helpers as admin_helpers
from django.contrib.admin.utils import flatten_fieldsets, lookup_field
from django.contrib.contenttypes.admin import GenericInlineModelAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import (
    FieldDoesNotExist,
    ImproperlyConfigured,
    PermissionDenied,
)
from django.db.models import Window
from django.db.models.functions import RowNumber
from django.forms import ModelChoiceField, ModelMultipleChoiceField
from django.forms.models import _get_foreign_key
from django.http.response import HttpResponseRedirectBase
from django.urls import Resolver404, resolve

from django_smartbase_admin.engine.const import ROW_CLASS_FIELD
from django_smartbase_admin.engine.fake_inline import (
    FakeInlineFilterOverrideMismatchError,
    SBAdminFakeInlineMixin,
    is_fake_inline_batch_safe,
)
from django_smartbase_admin.engine.inline_pagination import InlinePaginated
from django_smartbase_admin.mcp.bridge import (
    bind_sbadmin_request_data,
    captured_messages,
    ensure_messages_storage,
    set_request_payload,
)
from django_smartbase_admin.mcp.field_schema import (
    field_info,
    serialize_form_components,
)
from django_smartbase_admin.mcp.html_sanitize import sanitize_html
from django_smartbase_admin.mcp.form_encoding import (
    encode_form_components,
    form_component_errors,
)
from django_smartbase_admin.mcp.widgets import detail_widget_entries

logger = logging.getLogger(__name__)


def _pk_from_redirect(url: str):
    """Pull ``object_id`` out of a change-form redirect URL.

    Returns ``None`` for changelist redirects (no kwarg) or URLs that
    don't resolve in this URLconf.
    """
    try:
        match = resolve(url.split("?", 1)[0])
    except Resolver404:
        return None
    return match.kwargs.get("object_id")


# Messages storage now lives in ``bridge`` as :class:`MCPMessageStorage`,
# shared between the detail-write path here and the action invoke path
# in ``actions.py``. ``ensure_messages_storage`` / ``captured_messages``
# replace the old noop pair.


def _extract_form_errors(response) -> dict:
    """Pull ``form.errors`` / ``formset.errors`` out of a failed change-form
    response. The parent ``adminform`` lives under that key in context;
    inline formset errors come from ``inline_admin_formsets``."""
    components = SBAdminMCPDetailService._admin_form_components(response.context_data)
    return {"components": form_component_errors(components)}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SBAdminMCPDetailService:
    """Read/write entry points for one object on a ModelAdmin.

    All methods are stateless classmethods taking the resolved admin
    instance. Permissions and queryset isolation mirror the UI detail
    page exactly — anything the user couldn't reach there is reported
    missing here too.
    """

    # -- public ----------------------------------------------------------

    @classmethod
    def get_detail_fields(cls, admin, request, obj=None) -> list[str]:
        """Flat field list (form + readonly) the change form would show.

        Flattens fieldsets directly; ``ModelAdmin.get_fields`` would
        fall through to a form factory that advertises every editable
        model field, not just the fieldset declarations.
        """
        fieldsets = admin.get_fieldsets(request, obj)
        return [
            str(name) for name in flatten_fieldsets(fieldsets) if isinstance(name, str)
        ]

    @classmethod
    def get_detail_data(
        cls,
        admin,
        request,
        object_id,
        fields: list[str] | None = None,
    ) -> dict:
        """Read one object as the detail page would render it.

        Returns ``{"id": pk, "components": {"main": {"type": "form",
        "fields": ...}, <inline_name>: {"type": "formset", "fields": ...,
        "rows": [...], "truncated": <bool>}}}``. Related
        selections come back as ``{"value": <id>, "label": <display>}``
        (or a list of those for multi-select). Readonly fields always
        report ``required=False``.

        ``fields`` projects the parent row to a subset (unknown names
        raise ``LookupError``); inlines are always included with every
        field they declare. ``truncated`` flags paginated inlines
        where the queryset has more rows than ``per_page``.
        """
        set_request_payload(request, method="GET")
        response, obj = cls._run_change_view(admin, request, object_id)
        return {
            "id": obj.pk,
            **cls._render_change_form_payload(
                admin, request, ctx=response.context_data, obj=obj, fields=fields
            ),
        }

    @classmethod
    def get_add_form_data(
        cls,
        admin,
        request,
        fields: list[str] | None = None,
    ) -> dict:
        """Read the add page's empty bound form — schema for ``create_object``.

        Mirrors :meth:`get_detail_data` shape minus ``id``: the same named
        ``components`` and ``{value, readonly, required, widget[, widget_id]}``
        per field. Formset ``rows``
        come back empty (the add page renders blank extra rows that
        carry no persisted id).

        Use this to discover ``widget_id`` for autocomplete-backed
        fields before calling ``autocomplete`` + ``create_object``, or
        to inspect required fields / readonly flags ahead of a write.
        """
        response = cls._run_add_view(admin, request)
        return cls._render_change_form_payload(
            admin, request, ctx=response.context_data, obj=None, fields=fields
        )

    @classmethod
    def _run_add_view(cls, admin, request):
        """Drive ``_changeform_view`` GET for the add page.

        Counterpart to :meth:`_run_change_view`; gates on
        ``has_add_permission`` and returns the GET-rendered response.
        """
        if not admin.has_add_permission(request):
            raise PermissionDenied(
                f"User has no add permission on admin {type(admin).__name__}."
            )
        set_request_payload(request, method="GET")
        return admin._changeform_view(request, None, form_url="", extra_context=None)

    @classmethod
    def _render_change_form_payload(
        cls,
        admin,
        request,
        *,
        ctx,
        obj,
        fields: list[str] | None,
    ) -> dict:
        """Serialize and admin-enrich named components from a GET context."""
        available = cls.get_detail_fields(admin, request, obj)
        if fields is None:
            selected_set = set(available)
        else:
            unknown = [f for f in fields if f not in available]
            if unknown:
                raise LookupError(
                    f"Admin {admin.get_id()!r} has no detail fields {unknown}; "
                    f"available: {available}"
                )
            selected_set = set(fields)

        components = serialize_form_components(cls._admin_form_components(ctx))
        components["main"]["fields"] = cls._extract_detail_row(
            ctx["adminform"], obj, admin, selected_set, request
        )

        for iaf in ctx["inline_admin_formsets"]:
            inline = iaf.opts
            component_name = type(inline).__name__
            # ROW_CLASS_FIELD is a UI-only readonly row-CSS hook every
            # SBAdmin inline injects; strip it from the wire payload.
            inline_fields = {
                f
                for f in (inline.get_fields(request, obj) or [])
                if f != ROW_CLASS_FIELD
            }
            rows = [
                {
                    "id": inline_admin_form.original.pk,
                    "fields": cls._extract_detail_row(
                        inline_admin_form,
                        inline_admin_form.original,
                        inline,
                        inline_fields,
                        request,
                    ),
                }
                for inline_admin_form in iaf
                if inline_admin_form.original is not None
            ]
            # InlinePaginated caps rows at per_page; non-paginated
            # inlines have no paginator attribute (truncated=False).
            paginator = getattr(iaf.formset, "paginator", None)
            truncated = bool(paginator and paginator.count > len(rows))
            component = components[component_name]
            component["fields"] = {
                name: info
                for name, info in component["fields"].items()
                if name in inline_fields
            }
            component["rows"] = rows
            component["truncated"] = truncated

        payload = {
            "components": components,
        }
        if obj is not None:
            payload["widgets"] = detail_widget_entries(
                admin, request, ctx["adminform"], obj
            )
        return payload

    @staticmethod
    def _admin_form_components(ctx):
        """Adapt Django admin response context to named raw components."""
        components = {"main": ctx["adminform"].form}
        for inline_admin_formset in ctx["inline_admin_formsets"]:
            component_name = type(inline_admin_formset.opts).__name__
            if component_name in components:
                raise ImproperlyConfigured(
                    f"Duplicate MCP form component name {component_name!r}. "
                    "Admin inline component names use inline class names; "
                    "configure distinct inline classes."
                )
            components[component_name] = inline_admin_formset.formset
        return components

    @classmethod
    def update_detail_data(
        cls,
        admin,
        request,
        object_id,
        component_values: dict | None = None,
    ) -> dict:
        """Write one object through ``_changeform_view``.

        Mirrors :meth:`get_detail_data` — same form, same inline set,
        same permission gates. POST data is re-encoded from the
        GET-state bound forms with the caller's overrides layered on,
        so untouched fields restate their current values and Django's
        formset machinery sees a complete payload.

        ``component_values`` uses the same names as
        :meth:`get_detail_data`. Forms receive sparse field patches;
        formsets receive id-based update/delete operations or new rows.
        Components not mentioned retain their initial state.

        Values accept either raw scalars/pks or the
        ``{"value", "label"}`` envelope produced by
        :meth:`get_detail_data` (so agents can echo it back unchanged).

        Returns ``{"status": "ok", **fetch_detail_payload}`` on save,
        or ``{"status": "invalid", "errors": {...}}`` when validation
        fails (no DB write happens). Raises ``LookupError`` /
        ``PermissionDenied`` for the same conditions as
        :meth:`get_detail_data`, plus when an inline op references a
        row id that isn't on the object.
        """
        set_request_payload(request, method="GET")
        response, obj = cls._run_change_view(admin, request, object_id)
        if not admin.has_change_permission(request, obj):
            raise PermissionDenied(
                f"User has no change permission on object pk={object_id!r}."
            )
        return cls._write_through_changeform(
            admin,
            request,
            ctx=response.context_data,
            obj=obj,
            component_values=component_values or {},
        )

    @classmethod
    def create_object_data(
        cls,
        admin,
        request,
        component_values: dict | None = None,
    ) -> dict:
        """Create one object through ``_changeform_view``'s add flow.

        Symmetric counterpart to :meth:`update_detail_data` — same form,
        same inline set, same POST encoder. The empty bound form
        supplies field defaults so unspecified columns POST their
        documented default rather than blank.

        ``component_values`` uses the names returned by
        :meth:`get_add_form_data`. Forms receive sparse field patches and
        formsets receive new row dictionaries. Existing-row operations are
        rejected because there is nothing to update yet.

        Values accept the same envelope as the update path
        (``{"value", "label"}`` or raw scalars/pks).

        Returns ``{"status": "ok", **fetch_detail_payload}`` on save
        (the payload's ``id`` is the new object's pk), or
        ``{"status": "invalid", "errors": {...}}`` when validation
        fails. Raises ``PermissionDenied`` if the user has no add
        permission on the admin, ``LookupError`` for unknown field /
        inline names or for inline ops that carry ``id`` / ``_delete``.
        """
        response = cls._run_add_view(admin, request)
        return cls._write_through_changeform(
            admin,
            request,
            ctx=response.context_data,
            obj=None,
            component_values=component_values or {},
        )

    @classmethod
    def _write_through_changeform(
        cls,
        admin,
        request,
        *,
        ctx,
        obj,
        component_values: dict,
    ) -> dict:
        """Shared POST encode + dispatch + result shaping.

        ``obj`` is ``None`` for add flows; ``ctx`` is the GET-rendered
        change-form context adapted into the shared component encoder.
        """
        qd = encode_form_components(
            cls._admin_form_components(ctx),
            component_values,
            allow_existing_rows=obj is not None,
        )
        if obj is None:
            # Make ``response_add`` redirect to ``<...>_change/<pk>/``
            # instead of the changelist, so ``_pk_from_redirect`` can
            # recover the new pk.
            qd["_continue"] = "1"
        qd._mutable = False

        # Mirror POST onto ``request_data.request_post`` too — dependent
        # autocomplete widgets read forwarded values from there.
        set_request_payload(request, post=qd, method="POST")
        ensure_messages_storage(request)

        response = admin._changeform_view(
            request,
            str(obj.pk) if obj is not None else None,
            form_url="",
            extra_context=None,
        )

        messages = captured_messages(request)
        if isinstance(response, HttpResponseRedirectBase):
            refetch_pk = obj.pk if obj is not None else _pk_from_redirect(response.url)
            if refetch_pk is None:
                raise RuntimeError(
                    f"Admin {admin.get_id()!r} returned a success redirect "
                    f"without a resolvable object pk: {response.url!r}."
                )
            bind_sbadmin_request_data(
                request,
                view=admin.get_id(),
                object_id=str(refetch_pk),
                method="GET",
            )
            result = {
                "status": "ok",
                **cls.get_detail_data(admin, request, refetch_pk),
            }
            if messages:
                result["messages"] = messages
            return result

        result = {
            "status": "invalid",
            "errors": _extract_form_errors(response),
        }
        if messages:
            result["messages"] = messages
        return result

    # -- internals -------------------------------------------------------

    @classmethod
    def _run_change_view(cls, admin, request, object_id):
        """Drive ``_changeform_view``, return ``(response, obj)``.

        Pre-resolves the object so a missing target raises
        ``LookupError`` instead of falling through Django's
        "doesn't exist" branch — that branch calls ``message_user``,
        which crashes on the mock request (no messages backend).
        """
        if not admin.has_view_or_change_permission(request):
            raise PermissionDenied(
                f"User has no view permission on admin {type(admin).__name__}."
            )
        obj = admin.get_object(request, object_id)
        if obj is None:
            raise LookupError(
                f"Object pk={object_id!r} not found in admin {admin.get_id()!r}."
            )
        if not admin.has_view_or_change_permission(request, obj):
            raise PermissionDenied(
                f"User has no view permission on object pk={object_id!r}."
            )
        response = admin._changeform_view(
            request, str(obj.pk), form_url="", extra_context=None
        )
        return response, obj

    @classmethod
    def _detail_label_for_item(cls, form_field, item, request):
        """Picker label for one related object — same overrides the UI uses.

        Tries widget ``get_label`` first so SBAdmin autocomplete
        ``label_lambda`` flows through. Label-hook failures are logged
        so misconfigured hooks surface in production.
        """
        if form_field is not None:
            widget = getattr(form_field, "widget", None)
            get_label = getattr(widget, "get_label", None)
            if callable(get_label):
                try:
                    return get_label(request, item)
                except Exception:
                    logger.warning(
                        "Detail label hook %s.get_label failed for %r; "
                        "falling back to label_from_instance / str().",
                        type(widget).__name__,
                        item,
                        exc_info=True,
                    )
            label_from_instance = getattr(form_field, "label_from_instance", None)
            if callable(label_from_instance):
                try:
                    return label_from_instance(item)
                except Exception:
                    logger.warning(
                        "Detail label hook %s.label_from_instance failed "
                        "for %r; falling back to str().",
                        type(form_field).__name__,
                        item,
                        exc_info=True,
                    )
        return str(item)

    @classmethod
    def _detail_form_value(cls, bound_field, request):
        """Bound-field value, with ``{"value", "label"}`` for relations."""
        form_field = bound_field.field
        value = bound_field.value()

        if isinstance(form_field, ModelMultipleChoiceField):
            if not value:
                return []
            ids = list(value)
            try:
                objects = {
                    item.pk: item for item in form_field.queryset.filter(pk__in=ids)
                }
            except (ValueError, TypeError):
                # An id that can't match the related pk type (e.g. a non-numeric
                # value where the pk is integer) must not 500 the read-back; it
                # falls back to str() below as an unresolved id.
                objects = {}
            # Preserve submitted order; unresolved ids fall back to str()
            # rather than getting silently dropped.
            return [
                {
                    "value": pk,
                    "label": (
                        cls._detail_label_for_item(
                            form_field,
                            objects[resolved_pk],
                            request,
                        )
                        if (resolved_pk := form_field.prepare_value(pk)) in objects
                        else str(pk)
                    ),
                }
                for pk in ids
            ]

        if isinstance(form_field, ModelChoiceField):
            if value in (None, ""):
                return None
            try:
                item = form_field.queryset.get(pk=value)
            except form_field.queryset.model.DoesNotExist:
                return {"value": value, "label": str(value)}
            return {
                "value": value,
                "label": cls._detail_label_for_item(form_field, item, request),
            }

        return value

    @classmethod
    def _detail_readonly_value(cls, name, obj, model_admin, request):
        """Readonly value, coerced into the same shape editable fields use.

        ``model_admin`` is the admin owning the rendered form (parent
        admin for the main row, the inline instance for inline rows)
        so callable readonly methods resolve through ``lookup_field``
        like the change view does.
        """
        if obj is None:
            # Add page has no instance; lookup_field would deref obj._meta.
            return None
        f, _, value = lookup_field(name, obj, model_admin)
        if f is None:
            # Callable display methods often return mark_safe HTML.
            return sanitize_html(value)
        if f.many_to_many:
            related = getattr(obj, name).all()
            return [
                {
                    "value": item.pk,
                    "label": cls._detail_label_for_item(None, item, request),
                }
                for item in related
            ]
        if f.many_to_one or f.one_to_one:
            if value is None:
                return None
            return {
                "value": value.pk,
                "label": cls._detail_label_for_item(None, value, request),
            }
        return sanitize_html(value)

    @classmethod
    def _extract_detail_row(cls, admin_form, obj, model_admin, selected_set, request):
        """Walk an ``AdminForm`` / ``InlineAdminForm`` into a values dict.

        Same output shape for the parent row and each inline row.
        """
        field_data: dict[str, dict] = {}
        for fieldset in admin_form:
            for line in fieldset:
                for field in line:
                    if isinstance(field, admin_helpers.AdminReadonlyField):
                        name = field.field["name"]
                        if name not in selected_set:
                            continue
                        field_data[name] = field_info(
                            None,
                            cls._detail_readonly_value(name, obj, model_admin, request),
                            readonly=True,
                        )
                    else:
                        bound = field.field
                        name = bound.name
                        if name not in selected_set:
                            continue
                        field_data[name] = field_info(
                            bound.field,
                            cls._detail_form_value(bound, request),
                        )
        return field_data

    # ------------------------------------------------------------------
    # Inline-data batch read (read-only, grouped by parent pk).
    # Counterpart to ``SBAdminListAction.get_json_data()`` for related
    # rows; the only safe path to inline data outside the change form.
    # Used by ``mcp.list_rows(include_inlines=...)`` via
    # ``mcp/inlines.py:attach_inlines``.
    # ------------------------------------------------------------------

    @classmethod
    def get_data_for_parents(
        cls,
        inline,
        request,
        parent_pks,
        fields: list[str] | None = None,
    ) -> tuple[dict, list]:
        """Restricted, projected inline rows grouped by parent pk.

        Returns ``({parent_pk: [rows]}, [truncated_parent_pks])``. The
        ``truncated`` list is non-empty only when the inline declares
        pagination (``InlinePaginated``) and a parent had more rows
        than ``per_page``.

        Permissions, queryset restriction, join shape, and field
        allowlist are all enforced here; callers (MCP, future tooling)
        cannot bypass any of them by construction.
        """
        if not inline.has_view_or_change_permission(request, None):
            raise PermissionDenied(
                f"User has no view permission on inline {type(inline).__name__}."
            )

        parent_pks = list(parent_pks)
        if not parent_pks:
            return {}, []

        selected = cls._resolve_inline_data_fields(inline, request, fields)
        concrete, callables = cls._partition_inline_data_fields(inline, selected)
        pk_name = inline.model._meta.pk.name

        qs, parent_key = cls._restrict_to_parents(inline, request, parent_pks)
        cap = cls._get_inline_data_cap(inline)
        if cap is not None:
            # Window-cap only when the author already accepted
            # pagination cost; non-paginated inlines keep the cheap
            # unbounded plan.
            qs = qs.annotate(
                _rn=Window(
                    expression=RowNumber(),
                    partition_by=[parent_key],
                    order_by=inline.get_ordering(request),
                )
            ).filter(_rn__lte=cap + 1)

        if callables:
            rows = [
                cls._project_inline_instance(
                    inline, obj, parent_key, pk_name, concrete, callables
                )
                for obj in qs
            ]
        else:
            rows = list(qs.values(pk_name, parent_key, *concrete))

        grouped: dict = {}
        for r in rows:
            parent = r.pop(parent_key)
            # Mirror a custom pk name to a stable ``"id"`` key.
            if pk_name != "id" and "id" not in r and pk_name in r:
                r["id"] = r[pk_name]
            grouped.setdefault(parent, []).append(r)

        truncated: list = []
        if cap is not None:
            for pk, items in grouped.items():
                if len(items) > cap:
                    truncated.append(pk)
                    del items[cap:]

        return grouped, truncated

    @classmethod
    def _get_inline_data_cap(cls, inline) -> int | None:
        """Per-parent row cap. Only set when the author opted into
        pagination (``InlinePaginated.per_page``); otherwise unbounded —
        same trust model as the change-form rendering."""
        if isinstance(inline, InlinePaginated):
            return inline.per_page
        return None

    @classmethod
    def _restrict_to_parents(cls, inline, request, parent_pks):
        """Filter ``inline.get_queryset(request)`` to ``parent_pks`` and
        return ``(qs, parent_key_in_row_dict)``. Branch per join kind so
        callers never touch ORM column names."""
        qs = inline.get_queryset(request)
        if isinstance(inline, GenericInlineModelAdmin):
            ct = ContentType.objects.get_for_model(inline.parent_model)
            qs = qs.filter(
                **{
                    inline.ct_field: ct,
                    f"{inline.ct_fk_field}__in": list(parent_pks),
                }
            )
            return qs, inline.ct_fk_field
        if isinstance(inline, SBAdminFakeInlineMixin):
            if not is_fake_inline_batch_safe(type(inline)):
                raise FakeInlineFilterOverrideMismatchError(
                    f"Fake inline {type(inline).__name__} overrides only one of "
                    "filter_fake_inline_identifier_by_parent_instance / "
                    "filter_fake_inline_identifier_by_parent_pks; override both "
                    "(or neither) to keep batch read consistent with the "
                    "change form. See sbadmin.W004."
                )
            qs = inline.filter_fake_inline_identifier_by_parent_pks(qs, parent_pks)
            return qs, inline.fk_name
        fk = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
        qs = qs.filter(**{f"{fk.attname}__in": list(parent_pks)})
        return qs, fk.attname

    @classmethod
    def _resolve_inline_data_fields(
        cls, inline, request, requested: list[str] | None
    ) -> list[str]:
        available = list(inline.get_fields(request, None) or [])
        if requested is None:
            return available
        unknown = [f for f in requested if f not in available]
        if unknown:
            raise LookupError(
                f"Inline {type(inline).__name__} has no fields {unknown}; "
                f"available: {available}"
            )
        return list(requested)

    @classmethod
    def _partition_inline_data_fields(
        cls, inline, selected: list[str]
    ) -> tuple[list[str], list[str]]:
        """Split into model concrete fields (cheap ``.values()`` projection)
        and everything else (callable readonly methods, resolved per-instance)."""
        concrete: list[str] = []
        callables: list[str] = []
        for name in selected:
            try:
                inline.model._meta.get_field(name)
            except FieldDoesNotExist:
                callables.append(name)
            else:
                concrete.append(name)
        return concrete, callables

    @classmethod
    def _call_inline_readonly(cls, inline, name: str, obj):
        if obj is None:
            return None
        # Mirror Django readonly-field resolution: method on the inline
        # first (instance method OR classmethod — both bind to a
        # recognisable owner), then attribute/method on the model.
        method = getattr(inline, name, None)
        bound_to = getattr(method, "__self__", None)
        if callable(method) and bound_to in (inline, type(inline)):
            return sanitize_html(method(obj))
        value = getattr(obj, name, None)
        return sanitize_html(value() if callable(value) else value)

    @classmethod
    def _project_inline_instance(
        cls, inline, obj, parent_key, pk_name, concrete, callables
    ) -> dict:
        row = {pk_name: obj.pk, parent_key: getattr(obj, parent_key)}
        for name in concrete:
            row[name] = getattr(obj, name)
        for name in callables:
            row[name] = cls._call_inline_readonly(inline, name, obj)
        return row
