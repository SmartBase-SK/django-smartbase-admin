"""``list_rows(aggregate=...)`` — totals over the whole filtered set."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Count, F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from pydantic import ValidationError

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
    call_mcp_tool,
)
from django_smartbase_admin.plugins.nested import TabulatorNestedPlugin

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


def _by_parent(groups):
    """``group_by=["parent"]`` rows keyed by parent; the NULL group sorts
    first on SQLite but last on PostgreSQL."""
    return {row["group"]["parent"]: row["aggregates"] for row in groups}


class _Admin(SBAdmin):
    model = Folder
    search_fields = ("name",)
    # ``children`` is the reverse of the self-FK ``parent`` → a one-to-many
    # (multi-valued) field, used to exercise the join fan-out path.
    sbadmin_list_display = (
        "id",
        "name",
        "id_alias",
        SBAdminField(name="user_display", annotate=F("owner__username")),
        "count",
        "parent",
        "children",
        # Columns annotated over the to-many ``children`` relation, like an
        # order's payment states or its line-item total: ``child_name`` joins
        # one row per child, ``children_total`` aggregates them per folder.
        SBAdminField(name="child_name", annotate=F("children__name")),
        SBAdminField(name="children_total", annotate=Count("children")),
    )
    sbadmin_nested = {"parent_field": "parent"}

    # A method field with ``admin_order_field`` → backed by the ``id``
    # column via an annotation, so its ORM identifier is suffixed
    # (``id_alias_annt``), distinct from the agent-facing name ``id_alias``.
    @admin.display(ordering="id")
    def id_alias(self, obj):
        return obj.id

    # A method field whose public name equals the derived ``count`` aggregate
    # alias — used to exercise that nesting keeps a group column and an
    # equally-named aggregate from colliding.
    @admin.display(ordering="id")
    def count(self, obj):
        return obj.id


class _ChildOrderedAdmin(_Admin):
    # A project ``get_queryset()`` ordered over a to-many path, like
    # ``order_by("lines__position")``.
    def get_queryset(self, request=None):
        return super().get_queryset(request).order_by("children__name")


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

    def _tools(self, *, nested=False):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_mcp_request(user)
        request.request_data.configuration.plugins = (
            [TabulatorNestedPlugin] if nested else []
        )
        return SBAdminTools(request=request)

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
        # Group columns and aggregates are nested under separate keys.
        self.assertNotIn("aggregates", result)
        self.assertEqual(
            result["groups"],
            [
                {
                    "group": {"parent": None},
                    "aggregates": {"count": 2, "sum_id": a.pk + b.pk},
                },
                {
                    "group": {"parent": a.pk},
                    "aggregates": {"count": 2, "sum_id": sum(a_ids)},
                },
                {
                    "group": {"parent": b.pk},
                    "aggregates": {"count": 1, "sum_id": sum(b_ids)},
                },
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
            [{"group": {"id_alias": pk}, "aggregates": {"count": 1}} for pk in ids],
        )

    def test_group_by_annotated_field_with_nested_plugin(self):
        user_model = get_user_model()
        user_a = user_model.objects.create_user(username="a-user")
        user_b = user_model.objects.create_user(username="b-user")
        a = Folder.objects.create(name="a", owner=user_a)
        Folder.objects.create(name="a-child", parent=a, owner=user_a)
        Folder.objects.create(name="b", owner=user_b)

        result = self._tools(nested=True).list_rows(
            "filer_folder",
            fields=["id", "name"],
            group_by=["user_display"],
            aggregate=[{"fn": "count"}],
        )

        self.assertEqual(
            result["groups"],
            [
                {
                    "group": {"user_display": "a-user"},
                    "aggregates": {"count": 1},
                },
                {
                    "group": {"user_display": "b-user"},
                    "aggregates": {"count": 1},
                },
            ],
        )

    def test_aggregate_annotated_field_with_nested_plugin(self):
        user_model = get_user_model()
        user_a = user_model.objects.create_user(username="a-user")
        user_b = user_model.objects.create_user(username="b-user")
        a = Folder.objects.create(name="a", owner=user_a)
        Folder.objects.create(name="a-child", parent=a, owner=user_a)
        Folder.objects.create(name="b", owner=user_b)

        result = self._tools(nested=True).list_rows(
            "filer_folder",
            fields=["id", "name"],
            aggregate=[{"fn": "count", "field": "user_display"}],
        )

        self.assertEqual(result["aggregates"], {"count_user_display": 2})

    def test_group_key_equal_to_aggregate_alias_does_not_collide(self):
        # ``count`` is a method field whose public name equals the derived
        # ``count`` aggregate alias. Nesting the group column and the aggregate
        # under separate keys means they no longer share a dict, so both
        # survive — the group value under ``group.count`` and the metric under
        # ``aggregates.count``.
        ids = sorted(Folder.objects.create(name=n).pk for n in ("a", "b", "c"))

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            group_by=["count"],
            aggregate=[{"fn": "count"}],
        )

        self.assertEqual(
            result["groups"],
            [{"group": {"count": pk}, "aggregates": {"count": 1}} for pk in ids],
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

    def test_to_many_columns_in_fields_do_not_change_aggregates(self):
        # Showing a column annotated over a to-many relation used to put its
        # join into the aggregate query, so ``count`` counted join rows, not
        # folders (p with 3 children was counted 3 times). Totals must be the
        # same whichever columns are requested.
        p = Folder.objects.create(name="p")
        q = Folder.objects.create(name="q")
        child_ids = [
            Folder.objects.create(name=n, parent=p).pk for n in ("c1", "c2", "c3")
        ]
        aggregate = [{"fn": "count"}, {"fn": "sum", "field": "id"}]

        for extra in ([], ["child_name"], ["children_total"]):
            with self.subTest(fields=extra):
                fields = ["id", "name", *extra]
                result = self._tools().list_rows(
                    "filer_folder", fields=fields, aggregate=aggregate
                )
                self.assertEqual(
                    result["aggregates"],
                    {"count": 5, "sum_id": p.pk + q.pk + sum(child_ids)},
                )

                result = self._tools().list_rows(
                    "filer_folder",
                    fields=fields,
                    group_by=["parent"],
                    aggregate=aggregate,
                )
                self.assertEqual(
                    _by_parent(result["groups"]),
                    {
                        None: {"count": 2, "sum_id": p.pk + q.pk},
                        p.pk: {"count": 3, "sum_id": sum(child_ids)},
                    },
                )

    def test_aggregated_column_is_summed_and_grouped_per_object(self):
        # ``children_total`` aggregates a related set, like an order total
        # summed over its lines. Summing or grouping on it uses each folder's
        # own value, unaffected by the ``child_name`` join in ``fields``.
        p = Folder.objects.create(name="p")
        q = Folder.objects.create(name="q")
        for n in ("p1", "p2", "p3"):
            Folder.objects.create(name=n, parent=p)
        Folder.objects.create(name="q1", parent=q)
        fields = ["id", "name", "child_name"]

        result = self._tools().list_rows(
            "filer_folder",
            fields=fields,
            group_by=["parent"],
            aggregate=[{"fn": "sum", "field": "children_total"}, {"fn": "count"}],
        )
        self.assertEqual(
            _by_parent(result["groups"]),
            {
                None: {"sum_children_total": 4, "count": 2},
                p.pk: {"sum_children_total": 0, "count": 3},
                q.pk: {"sum_children_total": 0, "count": 1},
            },
        )

        result = self._tools().list_rows(
            "filer_folder",
            fields=fields,
            group_by=["children_total"],
            aggregate=[{"fn": "count"}],
        )
        self.assertEqual(
            result["groups"],
            [
                {"group": {"children_total": 0}, "aggregates": {"count": 4}},
                {"group": {"children_total": 1}, "aggregates": {"count": 1}},
                {"group": {"children_total": 3}, "aggregates": {"count": 1}},
            ],
        )

    def test_aggregated_column_ignores_admin_ordering_over_relation(self):
        # The per-object subquery starts from ``get_queryset()``. Keeping its
        # ``children__name`` ordering there would add that column to the
        # subquery's GROUP BY, split p's total into one row per child and
        # return 1.
        p = Folder.objects.create(name="p")
        for n in ("p1", "p2", "p3"):
            Folder.objects.create(name=n, parent=p)
        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, _ChildOrderedAdmin)
        MCPToolTestConfig().init_view_map()

        result = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            aggregate=[{"fn": "sum", "field": "children_total"}],
        )

        self.assertEqual(result["aggregates"], {"sum_children_total": 3})

    def test_invalid_group_by_specs_are_rejected(self):
        tools = self._tools()
        base = dict(view_id="filer_folder", fields=["id", "name"])

        # Undeclared group field.
        with self.assertRaises(LookupError):
            tools.list_rows(**base, aggregate=[{"fn": "count"}], group_by=["nope"])
        # group_by must be a list of names.
        with self.assertRaisesRegex(ValidationError, r"group_by\n.*valid list"):
            call_mcp_tool(
                tools, "list_rows", **base, aggregate=[{"fn": "count"}], group_by="name"
            )
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
        with self.assertRaisesRegex(ValidationError, r"aggregate\.0\.fn\n.*'sum'"):
            call_mcp_tool(
                tools, "list_rows", **base, aggregate=[{"fn": "median", "field": "id"}]
            )
        # Misspelled key: no fn, and the extra key is refused.
        with self.assertRaisesRegex(
            ValidationError, r"aggregate\.0\.function\n.*not permitted"
        ):
            call_mcp_tool(
                tools,
                "list_rows",
                **base,
                aggregate=[{"function": "sum", "field": "id"}],
            )
        # sum on a non-numeric (CharField) declared field.
        with self.assertRaises(ValueError):
            tools.list_rows(**base, aggregate=[{"fn": "sum", "field": "name"}])
        # Arbitrary / undeclared field name.
        with self.assertRaises(LookupError):
            tools.list_rows(**base, aggregate=[{"fn": "sum", "field": "nope"}])
        # Alias override is not allowed.
        with self.assertRaisesRegex(
            ValidationError, r"aggregate\.0\.as\n.*not permitted"
        ):
            call_mcp_tool(
                tools,
                "list_rows",
                **base,
                aggregate=[{"fn": "sum", "field": "id", "as": "x"}],
            )
