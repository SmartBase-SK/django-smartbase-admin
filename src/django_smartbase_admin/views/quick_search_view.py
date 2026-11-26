from django.http import Http404, JsonResponse
from django.views import View

from django_smartbase_admin.engine.quick_search import QuickSearchService


class QuickSearchView(View):
    def get(self, request, *args, **kwargs):
        configuration = request.request_data.configuration
        if not configuration.is_quick_search_enabled(request):
            raise Http404
        term = request.GET.get("q", "")
        sections = QuickSearchService(request).search(term)
        return JsonResponse({"query": term, "sections": sections})
