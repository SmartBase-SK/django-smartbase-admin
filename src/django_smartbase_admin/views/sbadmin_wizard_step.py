"""
One SBAdmin wizard step - title, model, form, and get/post/context hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Type

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.forms import BaseFormSet, Form
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.services.views import SBAdminViewService

if TYPE_CHECKING:
    from django_smartbase_admin.views.sbadmin_wizard_view import SBAdminWizardView


class SBAdminWizardStep:
    """
    Subclasses define one step. The wizard creates a new instance per request.

    **Attributes (in subclass):**
    - ``title`` - step title in the template
    - ``model`` - required, used for permission checks
    - ``form_class`` - Django ``Form`` / ``ModelForm``
    - ``requires_wizard_object`` - if True, missing object redirects to step 1

    **Lifecycle (handled by base class):**

    GET: ``get()`` → ``get_blocked_get_response()`` → ``requires_wizard_object``
    check → ``get_form()`` + ``get_formsets()`` → ``get_context_data()`` → render.

    POST: ``post()`` → ``requires_wizard_object`` check → ``get_form(POST)`` +
    ``get_formsets(POST)`` → validate all → ``form_valid(form, formsets)`` or
    ``form_invalid(form, formsets)``.
    """

    title: str = "Step"
    heading: str | None = None
    model = None
    form_class: Type[Form] | None = None
    formset_classes: list[type[BaseFormSet]] = []
    requires_wizard_object: bool = False
    template_name: str | None = None
    submit_button_label: str | None = None

    def __init__(self, wizard: SBAdminWizardView):
        self.wizard = wizard

    @property
    def request(self):
        return self.wizard.request

    def get_title(self) -> str:
        return str(self.title)

    def get_heading(self) -> str | None:
        """Heading shown before the step title.

        Falls back to the view-level ``wizard_step_heading``, then to
        ``model._meta.verbose_name``.
        """
        if self.heading is not None:
            return str(self.heading)
        if self.wizard.wizard_step_heading is not None:
            return str(self.wizard.wizard_step_heading)
        if self.model is not None:
            return str(self.model._meta.verbose_name)
        return None

    def get_template_name(self) -> str | None:
        return self.template_name

    def get_submit_button_label(self) -> str | None:
        """
        Primary submit button text. ``None`` means the default
        (not last step → "Next step", last step → "Finish").
        """
        return self.submit_button_label

    def get_blocked_get_response(self) -> HttpResponse | None:
        """
        Called at the beginning of GET. Return e.g. redirect when
        entering this step is blocked.
        """
        return None

    def get_form_class(self) -> Type[Form]:
        if self.form_class is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__}: set form_class or override get_form_class()."
            )
        return self.form_class

    def get_form_kwargs(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("request", self.request)
        kwargs.setdefault("view", self.wizard)
        return kwargs

    def get_form(self, data: Any = None, files: Any = None) -> Form:
        """Create a form instance, bound when *data* is provided."""
        form_class = self.get_form_class()
        kwargs = self.get_form_kwargs()
        if data is not None:
            kwargs["data"] = data
            kwargs["files"] = files
        return form_class(**kwargs)

    def get_formsets(
        self, data: Any = None, files: Any = None
    ) -> list[tuple[str, BaseFormSet]]:
        """Return ``[(title, formset_instance), ...]``.

        Override to declare formsets for this step.  On GET *data* is
        ``None`` (build unbound formsets with initial data); on POST
        *data* is ``request.POST``.
        """
        return []

    def get_context_data(
        self, context: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        """Build step-specific template context.

        ``context`` already contains the base context from the view.
        The step number and total are passed by the wizard as ``step_n``
        and ``steps_total`` via ``kwargs``.

        Formsets are injected automatically from ``get_formsets()``
        unless already provided via ``_bound_formsets`` kwarg (set by
        ``form_invalid``).
        """
        step_n = kwargs.get("step_n", 1)
        steps_total = kwargs.get("steps_total", 1)
        is_last = step_n >= steps_total

        submit_lbl = self.get_submit_button_label()
        if submit_lbl is None:
            submit_lbl = str(_("Finish")) if is_last else str(_("Next step"))

        context.update(
            {
                "sbadmin_wizard_step_title": self.get_title(),
                "sbadmin_wizard_submit_label": submit_lbl,
                "wizard_heading": self.get_heading(),
                "sbadmin_wizard_prev_step": step_n - 1 if step_n > 1 else None,
            }
        )

        nav = self.wizard._wizard_navigation_urls(step_n)
        nav = self.adjust_navigation(nav)
        context.update(nav)

        formsets = kwargs.get("_bound_formsets")
        if formsets is None:
            formsets = self.get_formsets()
        if formsets:
            context["wizard_formsets"] = formsets
            form = context.get("form")
            context["form_is_multipart"] = (
                form is not None and form.is_multipart()
            ) or any(
                any(f.is_multipart() for f in fs.forms)
                or fs.empty_form.is_multipart()
                for _, fs in formsets
            )
        return context

    def adjust_navigation(self, nav: dict[str, Any]) -> dict[str, Any]:
        """Adjust ``back_url``, ``wizard_footer_back_url``, ``prev_step_url``."""
        return nav

    def check_permission(self, request) -> None:
        """Raise ``PermissionDenied`` if the user may not access this step.

        Default: ``requires_wizard_object`` → check *change* on the object,
        otherwise check *add*.  Steps can override for custom logic.
        """
        model = self.model
        if model is None:
            raise ImproperlyConfigured(f"{self.__class__.__name__} must define model.")
        if self.requires_wizard_object:
            obj = self.wizard.get_wizard_object()
            if obj is not None and not SBAdminViewService.has_permission(
                request=request,
                view=self.wizard,
                model=model,
                obj=obj,
                permission="change",
            ):
                raise PermissionDenied
        else:
            if not SBAdminViewService.has_permission(
                request=request,
                view=self.wizard,
                model=model,
                obj=None,
                permission="add",
            ):
                raise PermissionDenied

    def _check_requires_wizard_object(self, request) -> HttpResponse | None:
        if self.requires_wizard_object and self.wizard.get_wizard_object() is None:
            messages.warning(request, _("Please complete the first step first."))
            return redirect(self.wizard.build_wizard_url(1))
        return None

    def get(self, request, *args: Any, **kwargs: Any) -> HttpResponse:
        blocked = self.get_blocked_get_response()
        if blocked is not None:
            return blocked
        obj_redirect = self._check_requires_wizard_object(request)
        if obj_redirect is not None:
            return obj_redirect
        form = self.get_form()
        context = self.wizard.get_context_data(form=form, **kwargs)
        return self.wizard.render_to_response(context)

    def post(self, request, *args: Any, **kwargs: Any) -> HttpResponse:
        obj_redirect = self._check_requires_wizard_object(request)
        if obj_redirect is not None:
            return obj_redirect
        form = self.get_form(data=request.POST, files=request.FILES)
        formsets = self.get_formsets(data=request.POST, files=request.FILES)
        if form.is_valid() and all(fs.is_valid() for _, fs in formsets):
            return self.form_valid(form, formsets)
        return self.form_invalid(form, formsets)

    def form_valid(self, form, formsets) -> HttpResponse:
        raise NotImplementedError(
            f"{self.__class__.__name__}.form_valid(form, formsets)"
        )

    def form_invalid(self, form, formsets) -> HttpResponse:
        context = self.wizard.get_context_data(form=form, _bound_formsets=formsets)
        return self.wizard.render_to_response(context)

    def register_autocomplete_views(self, request) -> None:
        """Register autocomplete widgets for this step's forms.

        Instantiates the main ``form_class`` and every ``formset_classes``
        row form with ``view=wizard`` and ``request=request`` so that
        ``SBAdminBaseFormInit.__init__`` triggers widget initialization
        and ``autocomplete_map`` registration.
        """
        init_kwargs = {"request": request, "view": self.wizard}
        form_class = self.get_form_class()
        form_class(**init_kwargs)

        for formset_class in self.formset_classes:
            formset_class.form(**init_kwargs)
