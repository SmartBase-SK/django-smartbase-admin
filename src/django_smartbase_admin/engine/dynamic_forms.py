import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from django import forms
from django.contrib.admin.helpers import Fieldset
from django.db import models
from django.http import HttpRequest
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

SBADMIN_DYNAMIC_REGION_PARAM = "sbadmin_dynamic_region"
SBADMIN_DYNAMIC_REGION_PREFIX_PARAM = "sbadmin_dynamic_region_prefix"
SBADMIN_DYNAMIC_REGION_ACTION = "sbadmin_dynamic_region"
SBADMIN_DYNAMIC_REGION_ADD_MODIFIER = "add"


def dynamic_region_initial_from_data(
    form_class: type[forms.Form],
    data: Any,
    form_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    probe_form = form_class(**(form_kwargs or {}))
    initial = {}
    files = {}
    for field_name, field in probe_form.fields.items():
        prefixed_name = probe_form.add_prefix(field_name)
        if field.widget.value_omitted_from_data(data, files, prefixed_name):
            continue
        initial[field_name] = field.widget.value_from_datadict(
            data, files, prefixed_name
        )
    return initial


class SBInactiveFieldPolicy(models.TextChoices):
    CLEAR = "clear", _("Clear")
    PRESERVE = "preserve", _("Preserve")


@dataclass(frozen=True)
class SBDynamicRegionState:
    name: str
    wrapper_id: str
    loading_id: str
    visible: bool
    active_field_names: frozenset[str]
    active_fields: tuple[str | tuple[str, ...], ...]


@dataclass(frozen=True)
class SBDynamicRegionContext:
    form: forms.Form
    region: "SBDynamicRegion"
    state: SBDynamicRegionState
    fieldset: Fieldset


class SBDynamicRegion:
    def __init__(
        self,
        *,
        name: str,
        trigger_fields: Iterable[str] = (),
        fields: Iterable[str] = (),
        is_visible: (
            Callable[[forms.Form, HttpRequest | None, "SBDynamicRegion"], bool] | None
        ) = None,
        get_active_fields: (
            Callable[
                [forms.Form, HttpRequest | None, "SBDynamicRegion"],
                Iterable[str | Iterable[str]],
            ]
            | None
        ) = None,
        inactive_field_policy: SBInactiveFieldPolicy = SBInactiveFieldPolicy.PRESERVE,
        template: str | None = None,
    ) -> None:
        self.name = name
        self.trigger_fields = tuple(trigger_fields)
        self.fields = tuple(fields)
        self.is_visible_callback = is_visible
        self.get_active_fields_callback = get_active_fields
        self.inactive_field_policy = inactive_field_policy
        self.template = template

    def is_visible(self, form: forms.Form, request: HttpRequest | None = None) -> bool:
        if self.is_visible_callback is None:
            return True
        return bool(self.is_visible_callback(form, request, self))

    def get_active_fields(
        self, form: forms.Form, request: HttpRequest | None = None
    ) -> Iterable[str | Iterable[str]]:
        if self.get_active_fields_callback is None:
            return self.fields
        return self.get_active_fields_callback(form, request, self)

    def get_wrapper_id(self, form: forms.Form) -> str:
        prefix = getattr(form, "prefix", None)
        pieces = ["sbadmin-dynamic-region"]
        if prefix:
            pieces.append(str(prefix))
        pieces.append(self.name)
        return slugify("-".join(pieces)).replace("_", "-")

    def resolve(
        self, form: forms.Form, request: HttpRequest | None = None
    ) -> SBDynamicRegionState:
        """Build visible field layout and active field names for this form."""
        visible = self.is_visible(form, request)
        known_field_names = set(self.fields) & set(form.fields)
        requested_layout = self.get_active_fields(form, request) if visible else ()
        active_field_names: set[str] = set()
        active_fields: list[str | tuple[str, ...]] = []
        for field in requested_layout:
            if isinstance(field, str):
                if field in known_field_names:
                    active_fields.append(field)
                    active_field_names.add(field)
                continue
            active_group = tuple(
                field_name for field_name in field if field_name in known_field_names
            )
            if active_group:
                active_fields.append(active_group)
                active_field_names.update(active_group)
        wrapper_id = self.get_wrapper_id(form)
        return SBDynamicRegionState(
            name=self.name,
            wrapper_id=wrapper_id,
            loading_id=f"{wrapper_id}-loading",
            visible=visible,
            active_field_names=frozenset(active_field_names),
            active_fields=tuple(active_fields),
        )


class SBAdminDynamicFormMixin:
    sbadmin_standalone_dynamic_regions = False

    def __init__(self, *args, **kwargs):
        threadsafe_request = kwargs.pop("request", None)
        if threadsafe_request is None:
            threadsafe_request = getattr(self, "request", None)
        if threadsafe_request is None:
            try:
                threadsafe_request = SBAdminThreadLocalService.get_request()
            except LookupError:
                threadsafe_request = None
        self.request = threadsafe_request
        super().__init__(*args, **kwargs)
        self.prepare_dynamic_regions(threadsafe_request)

    @staticmethod
    def dynamic_regions_for_request(
        form: forms.Form, region: SBDynamicRegion, request: HttpRequest
    ) -> list[SBDynamicRegion]:
        trigger_name = request.headers.get("HX-Trigger-Name")
        if not trigger_name:
            return [region]

        def matches_trigger(field_name):
            return trigger_name == field_name or trigger_name.endswith(f"-{field_name}")

        related_regions = [
            candidate
            for candidate in form.get_dynamic_regions(request)
            if any(
                matches_trigger(field_name) for field_name in candidate.trigger_fields
            )
        ]
        return related_regions or [region]

    @staticmethod
    def get_fieldset_fields(
        fieldset_data: dict[str, Any],
    ) -> tuple[str | tuple[str, ...], ...]:
        fields: list[str | tuple[str, ...]] = []
        for item in fieldset_data.get("fields") or ():
            if isinstance(item, SBDynamicRegion):
                fields.extend(item.fields)
            else:
                fields.append(item)
        return tuple(fields)

    @staticmethod
    def get_fieldset_dynamic_regions(
        fieldset_data: dict[str, Any],
    ) -> tuple[SBDynamicRegion, ...]:
        return tuple(
            item
            for item in fieldset_data.get("fields") or ()
            if isinstance(item, SBDynamicRegion)
        )

    def get_dynamic_regions(
        self, request: HttpRequest | None = None
    ) -> tuple[SBDynamicRegion, ...]:
        regions: list[SBDynamicRegion] = []
        object_id = self._sbadmin_dynamic_object_id()
        view = getattr(self, "view", None)
        if self.sbadmin_standalone_dynamic_regions:
            # Standalone form views own their dynamic region layout.
            fieldsets = self.get_sbadmin_fieldsets()
        elif view is not None and hasattr(view, "get_sbadmin_fieldsets"):
            # Admin forms use the current admin view layout for add/change.
            fieldsets = view.get_sbadmin_fieldsets(request, object_id)
        elif hasattr(self, "get_sbadmin_fieldsets"):
            # Plain SBAdmin forms can still declare regions on their own Meta.
            fieldsets = self.get_sbadmin_fieldsets()
        else:
            # Non-SBAdmin forms have no dynamic regions.
            fieldsets = ()
        for _name, data in fieldsets:
            regions.extend(self.get_fieldset_dynamic_regions(data))

        return tuple(regions)

    def get_dynamic_region(
        self, name: str, request: HttpRequest | None = None
    ) -> SBDynamicRegion | None:
        for region in self.get_dynamic_regions(request):
            if region.name == name:
                return region
        return None

    def get_dynamic_region_state(
        self, region: SBDynamicRegion, request: HttpRequest | None = None
    ) -> SBDynamicRegionState:
        cache = getattr(self, "_sbadmin_dynamic_region_states", {})
        if region.name not in cache:
            cache[region.name] = region.resolve(self, request)
            self._sbadmin_dynamic_region_states = cache
        return cache[region.name]

    def as_dynamic_region_fieldset(self, state: SBDynamicRegionState) -> Fieldset:
        return Fieldset(form=self, name=None, fields=state.active_fields, classes="")

    def get_dynamic_region_context(
        self, region: SBDynamicRegion, request: HttpRequest | None = None
    ) -> SBDynamicRegionContext:
        state = self.get_dynamic_region_state(region, request)
        return SBDynamicRegionContext(
            form=self,
            region=region,
            state=state,
            fieldset=self.as_dynamic_region_fieldset(state),
        )

    @staticmethod
    def get_fieldset_key(name: Any) -> str | None:
        return str(name) if name is not None else None

    def get_fieldsets_for_context(
        self, request: HttpRequest | None = None
    ) -> Iterable[tuple[str | None, dict[str, Any]]]:
        view = getattr(self, "view", None)
        if self.sbadmin_standalone_dynamic_regions and hasattr(
            self, "get_sbadmin_fieldsets"
        ):
            return self.get_sbadmin_fieldsets()
        if view is not None and hasattr(view, "get_sbadmin_fieldsets"):
            object_id = self._sbadmin_dynamic_object_id()
            return view.get_sbadmin_fieldsets(request, object_id)
        if hasattr(self, "get_sbadmin_fieldsets"):
            return self.get_sbadmin_fieldsets()
        return ()

    def get_fieldset_data_map(
        self, request: HttpRequest | None = None
    ) -> dict[str | None, dict[str, Any]]:
        fieldset_data_map = getattr(self, "_sbadmin_fieldset_data_map", None)
        if fieldset_data_map is None:
            fieldset_data_map = {
                self.get_fieldset_key(name): data
                for name, data in self.get_fieldsets_for_context(request)
            }
            self._sbadmin_fieldset_data_map = fieldset_data_map
        return fieldset_data_map

    def get_fieldset_context(
        self, fieldset: Fieldset, request: HttpRequest | None = None
    ) -> dict[str, Any]:
        fieldset_key = self.get_fieldset_key(fieldset.name)
        fieldset_data = self.get_fieldset_data_map(request).get(fieldset_key)
        if fieldset_data is None:
            return {}
        return {
            "fieldset": fieldset,
            "fieldset_layout": self.get_fieldset_layout(
                fieldset, fieldset_data, request
            ),
        }

    def get_fieldset_layout(
        self,
        fieldset: Fieldset,
        fieldset_data: dict[str, Any] | None,
        request: HttpRequest | None = None,
    ) -> tuple[dict[str, SBDynamicRegionContext | Fieldset], ...]:
        # A fieldset can mix normal fields with SBDynamicRegion markers. When it
        # does, build the exact render order as static Fieldset chunks separated
        # by region contexts, so templates can render each dynamic region in
        # place without losing the surrounding fields.
        layout = (fieldset_data or {}).get("fields") or ()
        if not any(isinstance(item, SBDynamicRegion) for item in layout):
            return ()

        chunks: list[dict[str, SBDynamicRegionContext | Fieldset]] = []
        static_fields: list[str | tuple[str, ...]] = []

        def flush_static_fields() -> None:
            # Consecutive static fields belong to one temporary Fieldset. Flush
            # them whenever a dynamic region starts, then keep collecting fields
            # after that region as a new chunk.
            if not static_fields:
                return
            chunks.append(
                {
                    "fieldset": Fieldset(
                        form=self,
                        name=getattr(fieldset, "name", None),
                        fields=tuple(static_fields),
                        classes=getattr(fieldset, "classes", ""),
                        description=getattr(fieldset, "description", None),
                    )
                }
            )
            static_fields.clear()

        for item in layout:
            if isinstance(item, SBDynamicRegion):
                flush_static_fields()
                chunks.append(
                    {"region": self.get_dynamic_region_context(item, request)}
                )
                continue
            if isinstance(item, (list, tuple)):
                group = tuple(field for field in item if isinstance(field, str))
                if group:
                    static_fields.append(group)
                continue
            static_fields.append(item)
        flush_static_fields()
        return tuple(chunks)

    def prepare_dynamic_regions(self, request: HttpRequest | None = None) -> None:
        regions = self.get_dynamic_regions(request)
        if not regions:
            return
        self._sbadmin_dynamic_region_states = {}
        active_fields: set[str] = set()
        inactive_by_policy: dict[SBInactiveFieldPolicy, set[str]] = {
            policy: set() for policy in SBInactiveFieldPolicy
        }
        for region in regions:
            state = self.get_dynamic_region_state(region, request)
            active_fields.update(state.active_field_names)
            inactive_by_policy[region.inactive_field_policy].update(
                set(region.fields) - set(state.active_field_names)
            )
            self._bind_dynamic_region_triggers(region, state, request)

        for policy, field_names in inactive_by_policy.items():
            self._apply_inactive_field_policy(
                policy, field_names - active_fields, request=request
            )

    def _clean_fields(self) -> None:
        inactive_field_names = getattr(
            self, "_sbadmin_skip_inactive_field_names", set()
        )
        if not inactive_field_names:
            return super()._clean_fields()

        inactive_fields = {
            field_name: self.fields.pop(field_name)
            for field_name in inactive_field_names
            if field_name in self.fields
        }
        try:
            return super()._clean_fields()
        finally:
            self.fields.update(inactive_fields)

    def _apply_inactive_field_policy(
        self,
        policy: SBInactiveFieldPolicy,
        field_names: set[str],
        *,
        request: HttpRequest | None = None,
    ) -> None:
        for field_name in field_names:
            if field_name not in self.fields:
                continue
            if policy == SBInactiveFieldPolicy.CLEAR:
                self.fields[field_name].required = False
                self._clear_bound_field_value(field_name)
                continue
            if policy == SBInactiveFieldPolicy.PRESERVE:
                inactive_field_names = getattr(
                    self, "_sbadmin_skip_inactive_field_names", set()
                )
                inactive_field_names.add(field_name)
                self._sbadmin_skip_inactive_field_names = inactive_field_names

    def _clear_bound_field_value(self, field_name: str) -> None:
        if not self.is_bound:
            self.initial[field_name] = self.fields[field_name].initial = None
            return
        data = self.data.copy()
        widget = self.fields[field_name].widget
        prefixed_name = self.add_prefix(field_name)
        data.pop(prefixed_name, None)
        for widget_name in getattr(widget, "widgets_names", ()):
            data.pop(f"{prefixed_name}{widget_name}", None)
        self.data = data

    def _bind_dynamic_region_triggers(
        self,
        region: SBDynamicRegion,
        state: SBDynamicRegionState,
        request: HttpRequest | None = None,
    ) -> None:
        endpoint = self._dynamic_region_endpoint(request)
        if not endpoint:
            return
        for field_name in region.trigger_fields:
            if field_name not in self.fields:
                continue
            widget = self.fields[field_name].widget
            attrs = widget.attrs
            attrs.setdefault("hx-get", endpoint)
            attrs.setdefault(
                "hx-trigger",
                getattr(widget, "dynamic_region_trigger_event", "change"),
            )
            attrs.setdefault("hx-target", f"#{state.wrapper_id}")
            attrs.setdefault("hx-include", "closest form")
            attrs.setdefault("hx-indicator", f"#{state.loading_id}")
            attrs.setdefault("hx-swap", "none")
            attrs.setdefault("hx-sync", "closest form:replace")
            hx_vals = {SBADMIN_DYNAMIC_REGION_PARAM: region.name}
            if self.prefix is not None:
                hx_vals[SBADMIN_DYNAMIC_REGION_PREFIX_PARAM] = self.prefix
            attrs.setdefault(
                "hx-vals",
                json.dumps(hx_vals),
            )

    def _dynamic_region_endpoint(self, request: HttpRequest | None = None) -> str:
        if self.sbadmin_standalone_dynamic_regions and request is not None:
            return request.path
        view = getattr(self, "view", None)
        if view is not None and hasattr(view, "get_action_url"):
            object_id = self._sbadmin_dynamic_object_id()
            modifier = (
                str(object_id) if object_id else SBADMIN_DYNAMIC_REGION_ADD_MODIFIER
            )
            return view.get_action_url(SBADMIN_DYNAMIC_REGION_ACTION, modifier)
        if request is not None:
            return request.path
        return ""

    def _sbadmin_dynamic_object_id(self) -> str | None:
        instance = getattr(self, "instance", None)
        pk = getattr(instance, "pk", None)
        return str(pk) if pk else None
