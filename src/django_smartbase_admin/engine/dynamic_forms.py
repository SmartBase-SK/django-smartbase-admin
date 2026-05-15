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

SBADMIN_DYNAMIC_REGION_PARAM = "sbadmin_dynamic_region"
SBADMIN_DYNAMIC_REGION_ACTION = "sbadmin_dynamic_region"
SBADMIN_DYNAMIC_REGION_ADD_MODIFIER = "add"


class SBInactiveFieldPolicy(models.TextChoices):
    IGNORE = "ignore", _("Ignore")
    CLEAR = "clear", _("Clear")
    PRESERVE = "preserve", _("Preserve")


@dataclass(frozen=True)
class SBDynamicRegionState:
    name: str
    wrapper_id: str
    loading_id: str
    visible: bool
    active_field_names: tuple[str, ...]
    active_fields: tuple[str | tuple[str, ...], ...]


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
        inactive_field_policy: SBInactiveFieldPolicy = SBInactiveFieldPolicy.IGNORE,
        template: str | None = None,
    ) -> None:
        self.name = name
        self.trigger_fields = tuple(trigger_fields)
        self.fields = tuple(self._normalize_field_name(field) for field in fields)
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
            return self.field_names
        return self.get_active_fields_callback(form, request, self)

    @property
    def field_names(self) -> tuple[str, ...]:
        return self.fields

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
        visible = self.is_visible(form, request)
        known_field_names = set(self.field_names)
        requested_layout = self._normalize_active_layout(
            self.get_active_fields(form, request) if visible else ()
        )
        active_field_names: list[str] = []
        active_name_set: set[str] = set()
        active_fields: list[str | tuple[str, ...]] = []
        for field in requested_layout:
            if isinstance(field, tuple):
                active_group = tuple(
                    field_name
                    for field_name in field
                    if field_name in known_field_names and field_name in form.fields
                )
                if active_group:
                    active_fields.append(active_group)
                    for field_name in active_group:
                        if field_name not in active_name_set:
                            active_name_set.add(field_name)
                            active_field_names.append(field_name)
                continue
            if field in known_field_names and field in form.fields:
                active_fields.append(field)
                if field not in active_name_set:
                    active_name_set.add(field)
                    active_field_names.append(field)
        wrapper_id = self.get_wrapper_id(form)
        return SBDynamicRegionState(
            name=self.name,
            wrapper_id=wrapper_id,
            loading_id=f"{wrapper_id}-loading",
            visible=visible,
            active_field_names=tuple(active_field_names),
            active_fields=tuple(active_fields),
        )

    @staticmethod
    def _normalize_field_name(field: str) -> str:
        if not isinstance(field, str):
            raise TypeError(
                "SBDynamicRegion.fields must be a flat iterable of field names."
            )
        return field

    @classmethod
    def _normalize_active_layout(
        cls, fields: Iterable[str | Iterable[str]]
    ) -> tuple[str | tuple[str, ...], ...]:
        return tuple(cls._normalize_active_layout_item(field) for field in fields)

    @staticmethod
    def _normalize_active_layout_item(
        field: str | Iterable[str],
    ) -> str | tuple[str, ...]:
        if isinstance(field, str):
            return field
        return tuple(str(field_name) for field_name in field)


class SBAdminDynamicFormMixin:
    sbadmin_include_view_dynamic_regions = True

    def value_from_data_or_initial(self, field_name: str) -> Any:
        if field_name not in self.fields:
            return None
        field = self.fields[field_name]
        if self.is_bound:
            data = self.data.copy()
            files = self.files
            return field.widget.value_from_datadict(
                data, files, self.add_prefix(field_name)
            )
        if field_name in self.initial:
            return self.initial[field_name]
        initial = field.initial
        return initial() if callable(initial) else initial

    def get_dynamic_regions(
        self, request: HttpRequest | None = None
    ) -> tuple[SBDynamicRegion, ...]:
        regions: list[SBDynamicRegion] = []
        for _name, data in self.get_fieldsets():
            regions.extend(data.get("dynamic_regions") or ())

        view = getattr(self, "view", None)
        if (
            self.sbadmin_include_view_dynamic_regions
            and view is not None
            and hasattr(view, "get_sbadmin_fieldsets")
        ):
            object_id = self._sbadmin_dynamic_object_id()
            try:
                for _name, data in view.get_sbadmin_fieldsets(request, object_id):
                    regions.extend(data.get("dynamic_regions") or ())
            except Exception:
                pass
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
                set(region.field_names) - set(state.active_field_names)
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

    def as_dynamic_region_fieldset(self, state: SBDynamicRegionState) -> Fieldset:
        return Fieldset(form=self, name=None, fields=state.active_fields, classes="")

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
            if policy in {SBInactiveFieldPolicy.IGNORE, SBInactiveFieldPolicy.PRESERVE}:
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
        prefixed_name = self.add_prefix(field_name)
        data[prefixed_name] = self._empty_value_for_field(self.fields[field_name])
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
            attrs.setdefault("hx-swap", "outerHTML")
            attrs.setdefault("hx-sync", "closest form:replace")
            attrs.setdefault(
                "hx-vals",
                json.dumps({SBADMIN_DYNAMIC_REGION_PARAM: region.name}),
            )

    def _dynamic_region_endpoint(self, request: HttpRequest | None = None) -> str:
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

    @staticmethod
    def _empty_value_for_field(field: forms.Field) -> Any:
        if isinstance(field, forms.BooleanField):
            return False
        if isinstance(field, forms.MultipleChoiceField):
            return []
        return ""
