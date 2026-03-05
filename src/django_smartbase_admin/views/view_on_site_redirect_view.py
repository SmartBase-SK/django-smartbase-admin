from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views import View

from django_smartbase_admin.engine.request import SBAdminViewRequestData


class ViewOnSiteRedirectView(View):
    """
    GET view: expects URL kwargs view and object_id.
    Resolves the admin from configuration, calls get_view_on_site_url(object_id),
    redirects to that URL.
    """

    def get(self, request, view, object_id, *args, **kwargs):
        request_data = SBAdminViewRequestData.from_request_and_kwargs(
            request, view=view, object_id=object_id
        )
        admin_instance = request_data.selected_view
        obj = get_object_or_404(admin_instance.model, pk=object_id)
        url = admin_instance.get_view_on_site_url(obj)
        if not url:
            raise Http404
        return HttpResponseRedirect(url)
