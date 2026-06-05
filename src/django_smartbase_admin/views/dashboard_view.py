from django.conf import settings
from django.template.response import TemplateResponse

from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import Action


class SBAdminDashboardView(SBAdminView):
    label = "Dashboard"
    view_id = "dashboard"
    menu_action = Action.DASHBOARD.value
    widgets = None
    title = None

    def __init__(self, title=None, widgets=None) -> None:
        super().__init__()
        self.widgets = widgets or self.widgets or []
        self.title = title

    def get_title(self):
        return self.title or settings.PROJECT_NAME

    @sbadmin_action
    def dashboard(self, request, modifier, object_id=None):
        context = self.get_global_context(request)
        context["direct_sub_views"] = self.widget_views
        context["title"] = self.get_title()
        return TemplateResponse(
            request,
            "sb_admin/actions/dashboard.html",
            context=context,
        )
