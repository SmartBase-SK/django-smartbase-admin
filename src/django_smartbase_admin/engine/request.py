from django.http import Http404
from django.middleware.csrf import get_token

from django_smartbase_admin.engine.const import GLOBAL_FILTER_DATA_KEY
from django_smartbase_admin.services.configuration import SBAdminConfigurationService


class SBAdminViewRequestData(object):
    view = None
    action = None
    modifier = None
    user = None
    object_id = None
    request_meta = None
    request_get = None
    request_post = None
    request_method = None
    global_filter = None
    global_filter_instance = None
    configuration = None
    selected_view = None
    session = None

    def __init__(
        self,
        view,
        action,
        modifier,
        user,
        object_id=None,
        request_meta=None,
        request_get=None,
        request_post=None,
        request_method=None,
        global_filter=None,
        session=None,
    ) -> None:
        super().__init__()
        self.view = view
        self.action = action
        self.modifier = modifier
        self.user = user
        self.object_id = object_id
        self.request_meta = request_meta or {}
        self.request_get = request_get or {}
        self.request_post = request_post or {}
        self.request_method = request_method
        self.global_filter = global_filter or {}
        self.session = session or {}

    def refresh_selected_view(self, request):
        self.configuration = SBAdminConfigurationService.get_configuration(self)
        if not self.view:
            self.view = self.configuration.default_view.get_view_id()
        try:
            self.selected_view = self.configuration.view_map[self.view]
        except KeyError:
            raise Http404
        self.configuration.init_configuration_dynamic(request, self)

    @classmethod
    def from_request_and_kwargs(cls, request, **kwargs):
        request_data = cls(
            view=kwargs.get("view"),
            action=kwargs.get("action"),
            modifier=kwargs.get("modifier"),
            object_id=kwargs.get("id"),
            user=request.user,
            request_meta=request.META,
            request_get=request.GET,
            request_post=request.POST,
            request_method=request.method,
            global_filter=request.session.get(GLOBAL_FILTER_DATA_KEY, None),
            session=request.session,
        )
        request.request_data = request_data
        request_data.refresh_selected_view(request)
        return request_data

    def set_global_filter_instance(self, global_filter_instance):
        self.global_filter_instance = global_filter_instance
