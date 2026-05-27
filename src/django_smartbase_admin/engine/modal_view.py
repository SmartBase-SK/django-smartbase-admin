from django import forms
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


class SBAdminActionError(Exception):
    """Raise inside an action modal hook to surface as a non-field form error."""


class ActionModalView(FormView):
    template_name = "sb_admin/partials/modal/modal_content.html"
    form_class = None
    modal_title = ""
    view = None
    render_notifications = True

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
                form_class, request.POST, form_kwargs=probe_kwargs
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
        if form.is_valid():
            try:
                return self.process_form_valid(request, form)
            except SBAdminActionError as e:
                form.add_error(None, str(e))
                return self.form_invalid(form)
        else:
            return self.form_invalid(form)

    def get_modal_title(self):
        return self.modal_title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modal_title"] = self.get_modal_title()
        return context


class ListActionModalView(ActionModalView):

    def process_form_valid(self, request, form):
        self.process_form_valid_list_selection_queryset(
            request, form, self.get_selection_queryset(request, form)
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
        pass


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
