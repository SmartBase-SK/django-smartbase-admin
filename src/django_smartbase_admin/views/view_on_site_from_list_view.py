"""
Redirect view for "View on site" from list: one request per click, no per-row queries.
Link in list points here with view + object_id; we resolve the frontend URL and redirect.
"""

from django.http import Http404, HttpResponseRedirect
from django.views import View

from django_smartbase_admin.engine.request import SBAdminViewRequestData


class ViewOnSiteFromListView(View):
    """
    GET view: expects URL kwargs view (model path, e.g. catalog/product) and object_id.
    Resolves the admin from configuration, calls get_sbadmin_view_on_site_url(object_id),
    redirects to that URL. Used by the list formatter so the list does no per-row URL resolution.
    """

    def get(self, request, view, object_id, *args, **kwargs):
        request_data = SBAdminViewRequestData.from_request_and_kwargs(
            request, view=view, object_id=object_id
        )
        admin_instance = request_data.selected_view
        url = admin_instance.get_sbadmin_view_on_site_url(object_id=object_id)
        if not url:
            raise Http404
        return HttpResponseRedirect(url)
