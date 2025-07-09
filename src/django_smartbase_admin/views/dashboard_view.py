from django.conf import settings
from django.template.response import TemplateResponse

from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.const import Action


class SBAdminDashboardView(SBAdminView):
    label = "Dashboard"
    view_id = "dashboard"
    menu_action = Action.DASHBOARD.value
    widgets = None
    title = None
    direct_sub_views = None

    def __init__(self, title=None, widgets=None) -> None:
        super().__init__()
        self.widgets = widgets
        self.title = title

    def get_title(self):
        return self.title or settings.PROJECT_NAME

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        super().init_view_dynamic(request, request_data, **kwargs)

        for view in self.sub_views:
            view.init_view_dynamic(request, request_data, **kwargs)

    def get_sub_views(self, configuration):
        self.direct_sub_views = []
        self.sub_views = []
        for idx, widget_view in enumerate(self.widgets):
            widget_view.widget_id = f"{self.get_id()}_{idx}"
            widget_view.init_widget_static(configuration)
            widget_view_sub_views = widget_view.get_sub_views(configuration) or []
            self.sub_views.append(widget_view)
            self.direct_sub_views.append(widget_view)
            self.sub_views.extend(widget_view_sub_views)
        return self.sub_views

    def dashboard(self, request, modifier):
        context = self.get_global_context(request)
        context["sub_views"] = self.sub_views
        context["direct_sub_views"] = self.direct_sub_views
        context["title"] = self.get_title()
        return TemplateResponse(
            request,
            "sb_admin/actions/dashboard.html",
            context=context,
        )
