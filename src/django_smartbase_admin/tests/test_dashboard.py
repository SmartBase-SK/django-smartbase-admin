from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth.models import User
from django.db.models import F
from django.test import RequestFactory, TestCase

from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.engine.dashboard import SBAdminDashboardListWidget
from django_smartbase_admin.engine.field import SBAdminField


class _DashboardWidget(SBAdminDashboardListWidget):
    model = User
    sbadmin_list_display = (SBAdminField(name="display_name", annotate=F("username")),)

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def init_actions(self, request):
        pass

    @admin.display(description="Display name")
    def display_name(self, object_id, value, **kwargs):
        return value


class TestSBAdminDashboardListWidget(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_init_view_dynamic_preserves_sbadmin_field_metadata(self):
        widget = _DashboardWidget()
        request = self.factory.get("/dashboard/")
        request.request_data = SimpleNamespace(configuration=SBAdminRoleConfiguration())

        widget.init_view_dynamic(request, request_data=request.request_data)
