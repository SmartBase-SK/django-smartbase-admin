from django.template.loader import render_to_string

from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.admin_view import SBAdminView


class SBAdminMediaView(SBAdminView):
    label = "Media"

    @sbadmin_action
    def list(self, request, modifier):
        return render_to_string("sb_admin/actions/media.html", context={})
