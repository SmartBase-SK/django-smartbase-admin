from django.http import HttpResponse
from django.views.generic import FormView
from django_htmx.http import trigger_client_event
from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.const import (
    IGNORE_LIST_SELECTION,
    TABLE_RELOAD_DATA_EVENT_NAME,
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

    def get_form_class(self):
        form_class = super().get_form_class()

        fake_form_class = type(
            form_class.__name__,
            (form_class,),
            {
                "view": self.view,
            },
        )

        return fake_form_class

    def post(self, request, *args, **kwargs):
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

    def get_object(self):
        if not hasattr(self, "_resolved_object"):
            modifier = self.kwargs.get("modifier")
            if modifier in (None, IGNORE_LIST_SELECTION):
                self._resolved_object = None
            else:
                self._resolved_object = (
                    self.get_object_queryset(self.request).filter(pk=modifier).first()
                )
        return self._resolved_object

    def dispatch(self, request, *args, **kwargs):
        modifier = kwargs.get("modifier")
        if modifier not in (None, IGNORE_LIST_SELECTION) and self.get_object() is None:
            return HttpResponse(self.not_found_message, status=404)
        return super().dispatch(request, *args, **kwargs)

    def process_form_valid(self, request, form):
        self.process_form_valid_object(request, form, self.get_object())
        return super().process_form_valid(request, form)

    def process_form_valid_object(self, request, form, obj):
        pass
