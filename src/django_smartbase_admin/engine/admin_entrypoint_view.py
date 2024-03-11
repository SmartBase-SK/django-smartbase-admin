from django.views import View

from django_smartbase_admin.services.views import SBAdminViewService


class SBAdminEntrypointView(View):
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return SBAdminViewService.delegate_to_action(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return SBAdminViewService.delegate_to_action(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return SBAdminViewService.delegate_to_action(request, *args, **kwargs)
