from django.http import HttpResponse
from django.views.generic import FormView
from django_htmx.http import trigger_client_event
from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.const import TABLE_RELOAD_DATA_EVENT_NAME


class ActionModalView(FormView):
    template_name = "sb_admin/partials/modal/modal_content.html"
    form_class = None
    modal_title = ""
    view = None

    def __init__(self, view=None, *args, **kwargs):
        self.view = view
        super().__init__(*args, **kwargs)

    def process_form_valid(self, request, form):
        response = HttpResponse()
        trigger_client_event(response, "hideModal", {})
        trigger_client_event(
            response,
            TABLE_RELOAD_DATA_EVENT_NAME,
            {},
        )
        return response

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
            return self.process_form_valid(request, form)
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
        response = super().process_form_valid(request, form)
        self.process_form_valid_list_selection_queryset(
            request, form, self.get_selection_queryset(request, form)
        )
        return response

    def get_selection_queryset(self, request, form):
        list_action = SBAdminListAction(self.view, request)
        return list_action.get_data_queryset().filter(
            list_action.get_selection_queryset()
        )

    def process_form_valid_list_selection_queryset(
        self, request, form, selection_queryset
    ):
        pass
