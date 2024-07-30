import json

from django.http import HttpResponse
from django.shortcuts import redirect
from django.views import View

from django_smartbase_admin.engine.const import (
    GLOBAL_FILTER_DATA_KEY,
    TABLE_RELOAD_DATA_EVENT_NAME,
)
from django_smartbase_admin.utils import is_htmx_request, querydict_to_dict


class GlobalFilterView(View):
    def post(self, request, *args, **kwargs):
        response = redirect(request.headers.get("referer", ""))
        if is_htmx_request(request.META):
            response = HttpResponse()
            response["HX-Trigger"] = json.dumps({TABLE_RELOAD_DATA_EVENT_NAME: ""})
        new_global_filter_data = querydict_to_dict(request.POST)
        request.request_data.global_filter = new_global_filter_data
        request.request_data.configuration.init_global_filter_form_instance(request)
        if request.request_data.global_filter_instance.is_valid():
            request.session[GLOBAL_FILTER_DATA_KEY] = new_global_filter_data
        response = request.request_data.process_global_filter_response(
            response, request
        )
        return response
