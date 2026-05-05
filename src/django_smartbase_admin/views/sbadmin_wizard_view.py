"""
Multi-step wizard where each step is an :class:`SBAdminWizardStep`.
"""

from __future__ import annotations

from typing import Any, Sequence, Type

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.views.generic import TemplateView

from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.views.sbadmin_wizard_step import SBAdminWizardStep


class SBAdminWizardView(SBAdminView, TemplateView):
    """
    ``wizard_steps`` - ordered step classes inheriting from :class:`SBAdminWizardStep`.
    Standalone SBAdmin view: does not depend on ``model_admin``.
    Step classes define their own ``model``.

    The view is a thin dispatcher — each step owns its form/formset creation,
    validation, context building, and save logic.
    """

    wizard_steps: Sequence[Type[SBAdminWizardStep]] = ()
    menu_action = "wizard"

    template_name = "sb_admin/wizard/wizard_step.html"

    wizard_step_heading: str | None = None
    wizard_step_field: str | None = None
    wizard_complete_field: str | None = None

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        self.request = request
        super().init_view_dynamic(request, request_data=request_data, **kwargs)
        self.register_autocomplete_views(request)

    def register_autocomplete_views(self, request) -> None:
        super().register_autocomplete_views(request)
        for step_cls in self.wizard_steps:
            step_cls(self).register_autocomplete_views(request)

    def dispatch(self, request, *args, **kwargs):
        if not self.wizard_steps:
            raise RuntimeError("SBAdminWizardView requires non-empty wizard_steps.")
        if getattr(request, "request_data", None) is not None:
            request.request_data.view = self.get_id()
            request.request_data.refresh_selected_view(request)
            request.sbadmin_selected_view = self
        self._check_wizard_permission(request)
        return super().dispatch(request, *args, **kwargs)

    def wizard(self, request, modifier):
        object_id = getattr(request.request_data, "object_id", None)
        kwargs = {"id": object_id} if object_id is not None else {}
        self.setup(request, **kwargs)
        return self.dispatch(request, **kwargs)

    def _check_wizard_permission(self, request):
        step_n = self.get_current_step()
        total = len(self.wizard_steps)
        if step_n < 1 or step_n > total:
            raise PermissionDenied
        step = self.get_step_object(step_n)
        step.check_permission(request)

    def get_current_step(self) -> int:
        raw = self.request.GET.get("step") or self.request.POST.get("step")
        try:
            s = int(raw) if raw is not None else 1
        except ValueError:
            s = 1
        n = len(self.wizard_steps) or 1
        return max(1, min(s, n))

    def get_step_object(self, step_1based: int | None = None) -> SBAdminWizardStep:
        idx = step_1based if step_1based is not None else self.get_current_step()
        return self.wizard_steps[idx - 1](self)

    def get_wizard_object(self):
        return None

    def get_template_names(self):
        step_template = self.get_step_object().get_template_name()
        if step_template:
            return [step_template]
        return [self.template_name]

    def _wizard_navigation_urls(self, step: int) -> dict[str, Any]:
        obj = self.get_wizard_object()
        obj_id = getattr(obj, "pk", None)
        back_url = None
        prev_wizard = self.build_wizard_url(step - 1, obj_id) if step > 1 else None
        if step > 1:
            back_url = prev_wizard
        return {
            "back_url": back_url,
            "prev_step_url": prev_wizard,
            "wizard_footer_back_url": back_url,
        }

    def get_context_data(self, **kwargs):
        step_n = self.get_current_step()
        step = self.get_step_object(step_n)
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "sbadmin_wizard_step": step_n,
                "sbadmin_wizard_steps_total": len(self.wizard_steps),
            }
        )
        obj = self.get_wizard_object()
        if obj is not None and getattr(obj, "pk", None):
            context["sbadmin_wizard_object_id"] = obj.pk
        context = step.get_context_data(
            context, step_n=step_n, steps_total=len(self.wizard_steps), **kwargs
        )
        if getattr(self.request, "sbadmin_selected_view", None):
            context.update(self.get_global_context(self.request))
        return context

    def get(self, request, *args, **kwargs) -> HttpResponse:
        step = self.get_step_object()
        return step.get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs) -> HttpResponse:
        step = self.get_step_object()
        return step.post(request, *args, **kwargs)

    @classmethod
    def build_wizard_url(cls, step: int, object_id: int | None = None) -> str:
        raise NotImplementedError(
            f"{cls.__name__}.build_wizard_url(step, object_id=None)"
        )

    def get_object_wizard_step(self, obj, default_step: int = 1) -> int:
        if not self.wizard_step_field:
            return default_step
        if not obj:
            return default_step
        value = getattr(obj, self.wizard_step_field, default_step)
        try:
            step = int(value)
        except (TypeError, ValueError):
            step = default_step
        max_step = len(self.wizard_steps) or 1
        return max(1, min(step, max_step))

    def is_object_wizard_completed(self, obj) -> bool:
        if not self.wizard_complete_field:
            return False
        if not obj:
            return False
        return bool(getattr(obj, self.wizard_complete_field, False))

    def update_object_wizard_state(
        self, obj, step: int | None = None, completed=None, commit: bool = True
    ):
        if not obj:
            return
        update_fields = []
        if step is not None and self.wizard_step_field:
            setattr(obj, self.wizard_step_field, step)
            update_fields.append(self.wizard_step_field)
        if completed is not None and self.wizard_complete_field:
            setattr(obj, self.wizard_complete_field, bool(completed))
            update_fields.append(self.wizard_complete_field)
        if update_fields and commit:
            if hasattr(obj, "modified"):
                update_fields.append("modified")
            obj.save(update_fields=update_fields)


__all__ = ("SBAdminWizardView", "SBAdminWizardStep")
