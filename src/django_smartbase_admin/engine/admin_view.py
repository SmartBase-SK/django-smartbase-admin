from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.engine.admin_base_view import (
    SBAdminBaseQuerysetMixin,
    SBAdminBaseView,
)
from django_smartbase_admin.engine.const import (
    Action,
    DEFAULT_PAGE_SIZE,
)
from django_smartbase_admin.services.configuration import SBAdminConfigurationService


class SBAdminView(SBAdminBaseQuerysetMixin, SBAdminBaseView):
    model = None
    label = None
    title = None
    icon = None
    description = None
    view_id = None
    menu_action = None
    fields = None
    list_display = None
    list_per_page = None
    ordering = None
    list_template_name = "sb_admin/actions/list.html"
    sub_views = None
    field_cache = None

    request_data = None

    def __init__(
        self,
        model=None,
        label=None,
        title=None,
        icon=None,
        description=None,
        view_id=None,
        menu_action=None,
        fields=None,
        list_display=None,
        list_per_page=None,
        ordering=None,
        list_template_name=None,
        global_filter_data_map=None,
        sub_views=None,
    ) -> None:
        super().__init__()
        self.model = model or self.model
        self.label = label or self.label
        self.title = title or self.title or self.label
        self.icon = icon or self.icon
        self.description = description or self.description
        self.view_id = view_id or self.view_id
        self.menu_action = menu_action or self.menu_action or Action.LIST.value
        self.fields = fields or self.fields or []
        self.list_display = list_display or self.list_display
        self.list_per_page = list_per_page or self.list_per_page or DEFAULT_PAGE_SIZE
        self.ordering = ordering or self.ordering
        self.list_template_name = list_template_name or self.list_template_name
        self.global_filter_data_map = (
            global_filter_data_map or self.global_filter_data_map
        )
        self.sub_views = sub_views or self.sub_views

    def get_id(self):
        return SBAdminConfigurationService.get_view_url_identifier(
            self.view_id or self.label
        )

    def get_sub_views(self, configuration):
        return self.sub_views

    def get_menu_label(self):
        return self.label

    def get_menu_view_url(self, request):
        return self.get_action_url(self.menu_action)

    def get_action_url(self, action, modifier="template"):
        return reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.get_id(),
                "action": action,
                "modifier": modifier,
            },
        )

    def keep_preserved_filters(self, request, url):
        changelist_filters = request.GET.get("_changelist_filters", None)
        return f"{url}{f'?_changelist_filters={changelist_filters}' if changelist_filters else ''}"

    def add_preserved_filters(self, request, url):
        changelist_filters = request.GET.get("_changelist_filters", None)
        return f"{url}{f'?{changelist_filters}' if changelist_filters else ''}"

    def get_back_url(self, request):
        return self.add_preserved_filters(
            request, self.get_action_url(Action.LIST.value)
        )

    def get_detail_change_response(self, request, msg_dict):
        if "_continue" in request.POST:
            msg = format_html(
                _(
                    "The {name} “{obj}” was changed successfully. You may edit it "
                    "again below."
                ),
                **msg_dict,
            )
            messages.success(request, msg)
            redirect_url = self.keep_preserved_filters(request, request.path)
            return HttpResponseRedirect(redirect_url)
        if "_save" in request.POST:
            msg = format_html(
                _("The {name} “{obj}” was changed successfully."), **msg_dict
            )
            messages.success(request, msg)
            redirect_url = self.get_back_url(request)
            return HttpResponseRedirect(redirect_url)
