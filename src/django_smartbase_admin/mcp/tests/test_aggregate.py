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
    search_fields = ("name",)
    # ``children`` is the reverse of the self-FK ``parent`` → a one-to-many
    # (multi-valued) field, used to exercise the join fan-out path.
    sbadmin_list_display = ("id", "name", "id_alias", "parent", "children")

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

    def test_aggregates_respect_full_text_search(self):
        ids = [Folder.objects.create(name=n).pk for n in ("alpha", "alpha-two")]
        Folder.objects.create(name="beta")  # excluded by the search term

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            full_text_search="alpha",
            aggregate=[{"fn": "count"}, {"fn": "sum", "field": "id"}],
        )

        # Aggregates must cover the searched set (2 rows), not all 3 — and
        # agree with the searched total_count.
        self.assertEqual(result["last_row"], 2)
        self.assertEqual(result["aggregates"], {"count": 2, "sum_id": sum(ids)})

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

    def test_group_by_breaks_totals_down_per_group(self):
        # Two parents (themselves parent=None), children nested under them →
        # group the count/sum by the parent FK so each parent surfaces once
        # with its own totals.
        a = Folder.objects.create(name="a")
        b = Folder.objects.create(name="b")
        a_ids = [Folder.objects.create(name=n, parent=a).pk for n in ("a1", "a2")]
        b_ids = [Folder.objects.create(name=n, parent=b).pk for n in ("b1",)]

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            group_by=["parent"],
            aggregate=[{"fn": "count"}, {"fn": "sum", "field": "id"}],
        )

        # No top-level scalar aggregates; a "groups" list instead, one row
        # per parent, ordered by the group column (NULLs first in sqlite).
        self.assertNotIn("aggregates", result)
        self.assertEqual(
            result["groups"],
            [
                {"parent": None, "count": 2, "sum_id": a.pk + b.pk},
                {"parent": a.pk, "count": 2, "sum_id": sum(a_ids)},
                {"parent": b.pk, "count": 1, "sum_id": sum(b_ids)},
            ],
        )

    def test_group_by_keys_rows_by_requested_name_not_orm_target(self):
        # ``id_alias`` is a method field whose ORM identifier is the annotation
        # alias ``id_alias_annt``. Grouping by it must still surface rows under
        # the agent-facing name ``id_alias`` (what the caller asked for), not
        # the internal target — otherwise the group key the caller reads back
        # doesn't match the field they grouped on.
        ids = sorted(Folder.objects.create(name=n).pk for n in ("a", "b", "c"))

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            group_by=["id_alias"],
            aggregate=[{"fn": "count"}],
        )

        self.assertNotIn("aggregates", result)
        self.assertEqual(
            result["groups"],
            [{"id_alias": pk, "count": 1} for pk in ids],
        )

    def test_aggregate_without_group_by_still_returns_scalar_dict(self):
        # Back-compat: the degenerate single-constant-group path keeps the
        # original scalar shape under "aggregates".
        ids = [Folder.objects.create(name=n).pk for n in ("a", "b")]
        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            aggregate=[{"fn": "count"}, {"fn": "sum", "field": "id"}],
        )
        self.assertNotIn("groups", result)
        self.assertEqual(result["aggregates"], {"count": 2, "sum_id": sum(ids)})

        # An empty filtered set still yields every requested alias (Django
        # drops the constant group from GROUP BY, so the rollup query always
        # returns one row) — not an empty dict.
        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            full_text_search="no-match",
            aggregate=[{"fn": "count"}, {"fn": "sum", "field": "id"}],
        )
        self.assertEqual(result["aggregates"], {"count": 0, "sum_id": None})

    def test_count_over_relation_does_not_inflate_sibling_sum(self):
        # A parent with 3 children: counting the multi-valued ``children``
        # relation adds a row-multiplying join. Run in one shared query, that
        # join would triple the parent's id in ``sum_id``. Each metric runs
        # in its own query, so the sum stays correct alongside the count.
        p = Folder.objects.create(name="p")
        child_ids = [
            Folder.objects.create(name=n, parent=p).pk for n in ("c1", "c2", "c3")
        ]
        all_ids = [p.pk, *child_ids]

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            aggregate=[
                {"fn": "count", "field": "children"},
                {"fn": "sum", "field": "id"},
            ],
        )

        # 3 children joined, but the sum is over the 4 real rows — not inflated
        # by the fan-out (a shared-query bug would give 3*p.pk + child sum).
        self.assertEqual(
            result["aggregates"],
            {"count_children": 3, "sum_id": sum(all_ids)},
        )

    def test_invalid_group_by_specs_are_rejected(self):
        tools = self._tools()
        base = dict(view_id="filer_folder", fields=["id", "name"])

        # Undeclared group field.
        with self.assertRaises(LookupError):
            tools.list_rows(**base, aggregate=[{"fn": "count"}], group_by=["nope"])
        # group_by without aggregate is meaningless.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, group_by=["name"])
        # Grouping on a multi-valued relation fans the rows out → rejected.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, aggregate=[{"fn": "count"}], group_by=["children"])

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
