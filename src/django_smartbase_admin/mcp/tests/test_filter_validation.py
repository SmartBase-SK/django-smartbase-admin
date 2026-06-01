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

        # 1. Misspelled key raises instead of returning every row.
        with self.assertRaises(ValueError) as ctx:
            tools.list_rows(
                "filer_folder",
                fields=["name"],
                filter_data={"from_date__gte": "2026-06-01"},
            )
        self.assertIn("from_date__gte", str(ctx.exception))

        # 2. Known key with wrong-shape value raises instead of
        #    fail-closing to an ambiguous empty result.
        with self.assertRaises(ValueError) as ctx:
            tools.list_rows(
                "filer_folder",
                fields=["name"],
                filter_data={"uploaded_at": "2026-06-01"},  # str, expects list
            )
        self.assertIn("DateFilterWidget", str(ctx.exception))

        # 3. Schema publishes the expected value shape so the agent
        #    doesn't have to guess between scalar / list / dict. The
        #    per-field filter block only names the widget category;
        #    ``value_shape`` / ``example`` live once in the top-level
        #    ``widget_shapes`` legend so we don't repeat them per column.
        result = tools.list_admins()
        entry = next(e for e in result["admin_views"] if e["view_id"] == "filer_folder")
        filter_info = next(f for f in entry["fields"] if f["name"] == "uploaded_at")[
            "filter"
        ]
        self.assertEqual(filter_info["widget"], "DateFilterWidget")
        self.assertNotIn("value_shape", filter_info)
        self.assertNotIn("example", filter_info)
        shape = result["widget_shapes"]["DateFilterWidget"]
        self.assertIn("start", shape["value_shape"])
        self.assertEqual(shape["example"], ["2026-06-01", "2026-06-30"])

    def test_date_open_ended_ranges_apply_the_present_bound(self):
        """A null bound is an open-ended range, not 'match nothing' — only
        both-null short-circuits to the empty result."""
        from datetime import datetime, timedelta
        from types import SimpleNamespace

        widget = DateFilterWidget()
        widget.field = SimpleNamespace(filter_field="uploaded_at")
        d1, d2 = datetime(2026, 3, 1), datetime(2026, 3, 10)

        def q(value):
            return widget.get_base_filter_query_for_parsed_value(None, value).children

        self.assertEqual(q([None, None]), [("pk__in", [])])
        self.assertEqual(q([d1, None]), [("uploaded_at__gte", d1)])
        self.assertEqual(q([None, d2]), [("uploaded_at__lte", d2 + timedelta(days=1))])
        self.assertEqual(
            q([d1, d2]),
            [
                ("uploaded_at__gte", d1),
                ("uploaded_at__lte", d2 + timedelta(days=1)),
            ],
        )
