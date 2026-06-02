"""``list_rows(aggregate=...)`` — totals over the whole filtered set."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.contrib import admin
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class _Admin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name", "id_alias")

    # A method field with ``admin_order_field`` → backed by the ``id``
    # column via an annotation, so its ORM identifier is suffixed
    # (``id_alias_annt``), distinct from the agent-facing name ``id_alias``.
    @admin.display(ordering="id")
    def id_alias(self, obj):
        return obj.id


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class AggregateTests(TestCase):
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

    def _tools(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user))

    def test_aggregates_span_full_filtered_set_not_the_page(self):
        ids = [Folder.objects.create(name=n).pk for n in ("a", "b", "c")]

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            page_size=1,  # tiny page on purpose
            aggregate=[
                {"fn": "count"},
                {"fn": "sum", "field": "id"},
                {"fn": "max", "field": "id"},
            ],
        )

        # Page is capped, but the aggregates cover every matching row.
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(
            result["aggregates"],
            {"count": 3, "sum_id": sum(ids), "max_id": max(ids)},
        )

    def test_field_name_resolves_to_orm_identifier(self):
        ids = [Folder.objects.create(name=n).pk for n in ("a", "b", "c")]

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            aggregate=[{"fn": "sum", "field": "id_alias"}],
        )

        # "id_alias" resolves to its ORM alias "id_alias_annt"; summing the
        # raw name would raise FieldError.
        self.assertEqual(result["aggregates"], {"sum_id_alias": sum(ids)})

    def test_invalid_aggregate_specs_are_rejected(self):
        tools = self._tools()
        base = dict(view_id="filer_folder", fields=["id", "name"])

        # Non-whitelisted function.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, aggregate=[{"fn": "median", "field": "id"}])
        # sum on a non-numeric (CharField) declared field.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, aggregate=[{"fn": "sum", "field": "name"}])
        # Arbitrary / undeclared field name.
        with self.assertRaises(LookupError):
            tools.list_rows(**base, aggregate=[{"fn": "sum", "field": "nope"}])
        # Alias override is not allowed.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, aggregate=[{"fn": "sum", "field": "id", "as": "x"}])
