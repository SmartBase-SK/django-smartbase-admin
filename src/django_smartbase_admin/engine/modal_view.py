import logging

from django import forms
from django.contrib import messages as django_messages
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.generic import FormView
from django_htmx.http import trigger_client_event
from django_smartbase_admin.engine.const import (
    IGNORE_LIST_SELECTION,
    TABLE_RELOAD_DATA_EVENT_NAME,
    Action,
)
from django_smartbase_admin.engine.dynamic_forms import (
    SBADMIN_DYNAMIC_REGION_PARAM,
    SBAdminDynamicFormMixin,
    SBDynamicRegionSource,
    dynamic_region_initial_from_data,
)
from django_smartbase_admin.utils import (
    render_notifications as render_notifications_html,
)

logger = logging.getLogger(__name__)


class SBAdminActionError(Exception):
    """Raise inside an action modal hook to surface as a non-field form error."""


class ActionModalView(FormView):
    template_name = "sb_admin/partials/modal/modal_content.html"
    form_class = None
    modal_title = ""
    view = None
    render_notifications = True

    # When True, the first valid submit runs ``get_confirmation_data``
    # and renders the confirmation step; ``process_form_valid`` only
    # runs on a second submit carrying ``_confirmed=1``.
    requires_confirmation: bool = False
    confirmation_template_name: str = "sb_admin/partials/modal/modal_confirmation.html"
    # ``.format(**data)``-ed at render time with the dict returned by
    # ``get_confirmation_data``.
    confirmation_message: str | None = None
    CONFIRMATION_POST_KEY = "_confirmed"

    def __init__(self, view=None, *args, **kwargs):
        self.view = view
        super().__init__(*args, **kwargs)

    def build_success_response(self, request):
        content = (
            render_notifications_html(request) if self.render_notifications else ""
        )
        response = HttpResponse(content)
        trigger_client_event(response, "hideModal", {})
        trigger_client_event(
            response,
            TABLE_RELOAD_DATA_EVENT_NAME,
            {},
        )
        return response

    def process_form_valid(self, request, form):
        return self.build_success_response(request)

    def build_dynamic_region_response(self, request, form, region_name):
        region = form.get_dynamic_region(region_name, request)
        if region is None:
            return HttpResponse("", status=404)
        rendered_regions = []
        for target_region in SBAdminDynamicFormMixin.dynamic_regions_for_request(
            form, region, request
        ):
            rendered_regions.append(
                render_to_string(
                    "sb_admin/includes/dynamic_region.html",
                    {
                        "dynamic_region": form.get_dynamic_region_context(
                            target_region, request, is_fragment=True
                        ),
                    },
                    request=request,
                )
            )
        html = "".join(rendered_regions)
        response = HttpResponse(html)
        trigger_client_event(
            response,
            "sbadminDynamicRegionUpdated",
            {"region": region.name},
        )
        return response

    def get_dynamic_region_form(self, request):
        form_class = self.get_form_class()
        form_kwargs = self.get_unbound_form_kwargs()
        probe_kwargs = dict(form_kwargs)
        form_kwargs["initial"] = {
            **form_kwargs.get("initial", {}),
            **dynamic_region_initial_from_data(
                form_class, request.POST, form_kwargs=probe_kwargs, files=request.FILES
            ),
        }
        return form_class(**form_kwargs)

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        form_class = self.get_form_class()
        if issubclass(form_class, SBAdminDynamicFormMixin):
            kwargs.update(
                {
                    "view": self.view,
                    "sbadmin_dynamic_region_source": SBDynamicRegionSource.FORM,
                    "sbadmin_dynamic_region_endpoint": self.request.path,
                }
            )
        from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit

        if issubclass(form_class, SBAdminBaseFormInit):
            kwargs.setdefault("view", self.view)
            request_data = getattr(self.request, "request_data", None)
            request_action = getattr(request_data, "action", None)
            if request_action and request_action != Action.AUTOCOMPLETE.value:
                kwargs["sbadmin_action_id"] = request_action
        return kwargs

    def get_unbound_form_kwargs(self):
        kwargs = self.get_form_kwargs()
        kwargs.pop("data", None)
        kwargs.pop("files", None)
        return kwargs

    def post(self, request, *args, **kwargs):
        if region_name := request.POST.get(SBADMIN_DYNAMIC_REGION_PARAM):
            return self.build_dynamic_region_response(
                request, self.get_dynamic_region_form(request), region_name
            )

        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)

        if (
            self.requires_confirmation
            and request.POST.get(self.CONFIRMATION_POST_KEY) != "1"
        ):
            try:
                preview = self.get_confirmation_data(request, form)
            except SBAdminActionError as e:
                form.add_error(None, str(e))
                return self.form_invalid(form)
            if preview is not None:
                return self._build_confirmation_response(request, form, preview)

        try:
            return self.process_form_valid(request, form)
        except SBAdminActionError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

    def get_confirmation_data(self, request, form) -> dict | None:
        """Preview data for the confirmation step.

        Return a JSON-safe dict, or ``None`` to skip the confirmation
        step entirely. Raise ``SBAdminActionError`` to surface the
        preview failure as a non-field form error.
        """
        return None

    def get_confirmation_message(self, request, form, data) -> str | None:
        """Format ``confirmation_message`` with ``data``.

        A missing placeholder logs a warning and falls back to the raw
        template instead of 500-ing — the confirmation flow stays usable
        when ``get_confirmation_data`` drifts out of sync with the
        template string.
        """
        if self.confirmation_message is None:
            return None
        try:
            return self.confirmation_message.format(**data)
        except (KeyError, IndexError) as exc:
            logger.warning(
                "confirmation_message %r missing placeholder %s on %s",
                self.confirmation_message,
                exc,
                self.__class__.__name__,
            )
            return self.confirmation_message

    def _build_confirmation_response(self, request, form, data):
        message = self.get_confirmation_message(request, form, data)
        trigger_data = {**data}
        if message is not None:
            # MCP reads the formatted line off the trigger payload.
            trigger_data["_message"] = message

        # Replay the original POST verbatim (getlist preserves
        # multi-select values); drop the confirmation flag since we add
        # it fresh below.
        form_data_items = [
            (key, value)
            for key in request.POST
            if key != self.CONFIRMATION_POST_KEY
            for value in request.POST.getlist(key)
        ]

        response = HttpResponse(
            render_to_string(
                self.confirmation_template_name,
                {
                    "form": form,
                    "modal_title": self.get_modal_title(),
                    "data": data,
                    "message": message,
                    "modal_view": self,
                    "form_data_items": form_data_items,
                    "confirmation_post_key": self.CONFIRMATION_POST_KEY,
                },
                request=request,
            )
        )
        trigger_client_event(response, "sbadminConfirmationRequired", trigger_data)
        return response

    def get_modal_title(self):
        return self.modal_title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modal_title"] = self.get_modal_title()
        return context


class ListActionModalView(ActionModalView):

    # Opt-in: subclasses set this to e.g. ``"Renamed {count} record{plural}."``
    # to auto-emit a success message when ``process_form_valid_list_selection_queryset``
    # returns an int. Default ``None`` preserves existing behavior (no
    # auto-message); subclasses still control timing via ``messages.success``.
    success_message: str | None = None

    def process_form_valid(self, request, form):
        affected = self.process_form_valid_list_selection_queryset(
            request, form, self.get_selection_queryset(request, form)
        )
        if affected is not None and self.success_message:
            django_messages.success(
                request,
                self.success_message.format(
                    count=affected,
                    plural="" if affected == 1 else "s",
                ),
            )
        return super().process_form_valid(request, form)

    def get_selection_queryset(self, request, form):
        list_action = self.view.sbadmin_list_action_class(self.view, request)
        return list_action.get_data_queryset().filter(
            list_action.get_selection_queryset(), list_action.get_filter_from_request()
        )

    def process_form_valid_list_selection_queryset(
        self, request, form, selection_queryset
    ):
        """Operate on the selection queryset.

        Return the affected count (e.g. from ``qs.update(...)`` /
        ``qs.delete()[0]``) to auto-emit ``success_message``. Return
        ``None`` to skip; subclasses can still call ``messages.success``
        themselves.
        """
        return None


class RowActionModalView(ActionModalView):
    not_found_message = "Not found."

    def get_object_queryset(self, request):
        return self.view.get_queryset(request)

    def get_object_id(self):
        if hasattr(self.request, "request_data"):
            object_id = getattr(self.request.request_data, "object_id", None)
            if object_id is not None:
                return object_id
        return self.kwargs.get("modifier")

    def get_object(self):
        if not hasattr(self, "_resolved_object"):
            object_id = self.get_object_id()
            if object_id in (None, IGNORE_LIST_SELECTION):
                self._resolved_object = None
            else:
                self._resolved_object = (
                    self.get_object_queryset(self.request).filter(pk=object_id).first()
                )
        return self._resolved_object

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        obj = self.get_object()
        if obj is not None and issubclass(self.get_form_class(), forms.ModelForm):
            kwargs["instance"] = obj
        return kwargs

    def dispatch(self, request, *args, **kwargs):
        object_id = self.get_object_id()
        if object_id not in (None, IGNORE_LIST_SELECTION) and self.get_object() is None:
            return HttpResponse(self.not_found_message, status=404)
        return super().dispatch(request, *args, **kwargs)

    def process_form_valid(self, request, form):
        self.process_form_valid_object(request, form, self.get_object())
        return super().process_form_valid(request, form)

    def process_form_valid_object(self, request, form, obj):
        pass
