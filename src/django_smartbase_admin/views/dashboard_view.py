from django import forms
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

    def get_widget_id(self, widget, index):
        return f"{self.get_id()}_{index}"

    def get_dashboard_media(self, request, widget_views=None):
        media = forms.Media()
        if widget_views is None:
            widget_views = self.get_widget_views(request)
        for widget in widget_views:
            if hasattr(widget, "get_media"):
                media += widget.get_media()
        return media

    @sbadmin_action
    def dashboard(self, request, modifier, object_id=None):
        context = self.get_global_context(request)
        widget_views = self.get_widget_views(request, object_id)
        context["direct_sub_views"] = widget_views
        context["dashboard_media"] = self.get_dashboard_media(request, widget_views)
        context["title"] = self.get_title()
        return TemplateResponse(
            request,
            "sb_admin/actions/dashboard.html",
            context=context,
        )
