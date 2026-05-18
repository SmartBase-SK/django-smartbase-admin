from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views import View

from django_smartbase_admin.engine.request import SBAdminViewRequestData


class ViewOnSiteRedirectView(View):
    """Resolve a list-row "View on site" link to the object's frontend URL.

    Both the URL and the object lookup go through the admin's restricted
    queryset, so ``restrict_queryset`` / `has_view_permission` are honored.
    The stock Django ``r/<ct>/<id>/`` route is shadowed in ``SBAdminSite``
    so this view is the only legitimate entry point.
    """

    def get(self, request, view, object_id, *args, **kwargs):
        request_data = SBAdminViewRequestData.from_request_and_kwargs(
            request, view=view, object_id=object_id
        )
        admin_instance = request_data.selected_view
        if admin_instance is None:
            raise Http404

        admin_instance.init_view_dynamic(request, request_data)

        if not admin_instance.has_view_permission(request):
            raise PermissionDenied

        obj = get_object_or_404(admin_instance.get_queryset(request), pk=object_id)

        get_absolute_url = getattr(obj, "get_absolute_url", None)
        url = get_absolute_url() if callable(get_absolute_url) else None
        if not url:
            raise Http404
        return HttpResponseRedirect(url)
