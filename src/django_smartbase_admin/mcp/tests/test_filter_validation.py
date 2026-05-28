"""Unknown filter keys must raise; discovery surfaces ``value_shape``."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import DateFilterWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class _Admin(SBAdmin):
    model = Folder
    sbadmin_list_display = (
        "id",
        "name",
        SBAdminField(
            name="uploaded_at",
            filter_field="uploaded_at",
            filter_widget=DateFilterWidget(),
        ),
    )


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FilterValidationTests(TestCase):
    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, _Admin)
        MCPToolTestConfig().init_view_map()

    def tearDown(self):
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def test_unknown_filter_raises_and_schema_publishes_shape(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))

        # 1. Silent-drop guard: misspelled key raises instead of
        #    returning every row.
        with self.assertRaises(ValueError) as ctx:
            tools.list_rows(
                "filer_folder",
                fields=["name"],
                filter_data={"from_date__gte": "2026-06-01"},
            )
        self.assertIn("from_date__gte", str(ctx.exception))

        # 2. Schema publishes the expected value shape so the agent
        #    doesn't have to guess between scalar / list / dict.
        entry = next(e for e in tools.list_admins() if e["view_id"] == "filer_folder")
        filter_info = next(f for f in entry["fields"] if f["name"] == "uploaded_at")[
            "filter"
        ]
        self.assertIn("start", filter_info["value_shape"])
        self.assertEqual(filter_info["example"], ["2026-06-01", "2026-06-30"])
