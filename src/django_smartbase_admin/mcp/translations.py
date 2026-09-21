"""MCP detail adapter for the built-in model translation view."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction

from django_smartbase_admin.engine.const import TRANSLATION_MODEL_KEY
from django_smartbase_admin.mcp.bridge import set_request_payload
from django_smartbase_admin.mcp.field_schema import serialize_form_component
from django_smartbase_admin.mcp.form_encoding import (
    bind_form_components,
    encode_form_components,
    form_component_errors,
)


@dataclass
class _TranslationComponent:
    form: object
    language_code: str
    model_table: str
    public_fields: set[str]


class SBAdminMCPTranslationService:
    """Read and sparsely update ``ModelTranslationView`` language forms."""

    technical_fields = frozenset({"id", "language_code"})

    @classmethod
    def get_detail_fields(cls, view, request=None, obj=None) -> list[str]:
        fields = []
        for model_fields in view.get_translated_fields().values():
            for model_field in model_fields:
                if model_field.name not in fields:
                    fields.append(model_field.name)
        return fields

    @classmethod
    def get_detail_data(cls, view, request, object_id, fields=None) -> dict:
        obj = cls._get_object(view, request, object_id, change=False)
        components = cls._get_components(view, request, obj)
        available_fields = set(cls.get_detail_fields(view))
        selected_fields = available_fields if fields is None else set(fields)
        unknown_fields = sorted(selected_fields - available_fields)
        if unknown_fields:
            raise LookupError(
                f"Translation view {view.get_id()!r} has no detail fields "
                f"{unknown_fields}; available: {sorted(available_fields)}."
            )

        serialized = {}
        for name, component in components.items():
            entry = serialize_form_component(
                component.form,
                field_names=component.public_fields & selected_fields,
            )
            entry["language_code"] = component.language_code
            entry["translation_model"] = component.model_table
            serialized[name] = entry
        return {"id": obj.pk, "components": serialized}

    @classmethod
    def update_detail_data(
        cls,
        view,
        request,
        object_id,
        component_values=None,
    ) -> dict:
        obj = cls._get_object(view, request, object_id, change=True)
        components = cls._get_components(view, request, obj)
        values = component_values or {}
        if not isinstance(values, dict):
            raise TypeError("component_values must be a dictionary.")
        unknown_components = sorted(set(values) - set(components))
        if unknown_components:
            raise LookupError(
                f"Unknown translation components: {unknown_components}; "
                f"available: {sorted(components)}."
            )

        bound_components = {}
        for name, overrides in values.items():
            component = components[name]
            encoded = encode_form_components(
                {name: component.form},
                {name: overrides},
            )
            bound_components[name] = bind_form_components(
                {name: component.form}, encoded
            )[name]

        errors = form_component_errors(bound_components)
        if errors["global"] or errors["components"]:
            return {"status": "invalid", "errors": errors}

        with transaction.atomic():
            for form in bound_components.values():
                view.save_translation(request, form)

        return {
            "status": "ok",
            **cls.get_detail_data(view, request, obj.pk),
        }

    @classmethod
    def _get_object(cls, view, request, object_id, *, change):
        if not view.has_view_or_change_permission(request):
            raise PermissionDenied(
                f"User has no view permission on translation view "
                f"{view.get_id()!r}."
            )
        obj = view.get_queryset(request).filter(pk=object_id).first()
        if obj is None:
            raise LookupError(
                f"Object pk={object_id!r} not found in translation view "
                f"{view.get_id()!r}."
            )
        if not view.has_view_or_change_permission(request, obj):
            raise PermissionDenied(
                f"User has no view permission on object pk={object_id!r}."
            )
        if change and not view.has_change_permission(request, obj):
            raise PermissionDenied(
                f"User has no change permission on object pk={object_id!r}."
            )
        return obj

    @classmethod
    def _get_components(cls, view, request, obj):
        set_request_payload(request, post={}, method="GET")
        translation_forms = view.get_translation_forms(request, obj.pk)

        main_language_code = view.get_display_language_codes(
            request, include_main=True
        )[0]
        components = {}
        for language_code, forms in translation_forms.items():
            for form in forms:
                model_table = getattr(form, TRANSLATION_MODEL_KEY)
                name = f"{model_table}:{language_code}"
                if name in components:
                    raise RuntimeError(
                        f"Duplicate translation component {name!r} on "
                        f"{view.get_id()!r}."
                    )
                # Technical identity fields are transport details, and the
                # source language is intentionally read-only in the browser.
                # ``disabled`` makes those same constraints explicit in the
                # MCP schema and write encoder.
                for field_name, field in form.fields.items():
                    if (
                        field_name in cls.technical_fields
                        or language_code == main_language_code
                    ):
                        field.disabled = True
                form.instance.master_id = obj.pk
                components[name] = _TranslationComponent(
                    form=form,
                    language_code=language_code,
                    model_table=model_table,
                    public_fields=set(form.fields) - cls.technical_fields,
                )
        return components
