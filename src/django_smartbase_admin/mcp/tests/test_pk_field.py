"""A model's primary key is exposed as a real, filterable/sortable column
for MCP even when the admin doesn't declare it — closing the round-trip
between the ``id`` every row carries and what ``list_rows`` accepts as input.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.contrib import admin
from django.contrib.sessions.models import Session
from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from django.utils import timezone
from filer.models import Folder

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class _PkOmittedAdmin(SBAdmin):
    """Pk deliberately absent from ``list_display`` — the MCP layer
    should synthesize it."""

    model = Folder
    sbadmin_list_display = ("name",)


class _PkDeclaredAdmin(SBAdmin):
    """Pk explicitly declared — no synthetic column should be added."""

    model = Folder
    list_display = ("id", "name")


class _PkAliasFilterFieldAdmin(SBAdmin):
    """Pk exposed under a different name but filtered via ``filter_field="id"``
    — the synthetic column must not duplicate that filter_field."""

    model = Folder
    sbadmin_list_display = (
        SBAdminField(name="public_id", annotate=F("id"), filter_field="id"),
        "name",
    )


class _PkMethodOrderingAdmin(SBAdmin):
    """Pk reached through a display method ordered on it — same collision."""

    model = Folder
    sbadmin_list_display = ("id_label", "name")

    @admin.display(ordering="id")
    def id_label(self, obj):
        return f"#{obj.id}"


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class PrimaryKeyFieldTests(TestCase):
    admin_class = _PkOmittedAdmin

    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, self.admin_class)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def _tools(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user))

    def test_schema_surfaces_synthetic_pk_with_widget_and_shape(self):
        result = self._tools().list_admins()
        entry = next(e for e in result["admin_views"] if e["view_id"] == "filer_folder")
        fields_by_name = {f["name"]: f for f in entry["fields"]}

        self.assertIn("id", fields_by_name)
        pk_field = fields_by_name["id"]
        # Synthetic, so it's hidden by default but real enough to filter.
        self.assertEqual(pk_field.get("list_visible"), False)
        self.assertEqual(pk_field["filter"]["widget"], "PrimaryKeyFilterWidget")

        shape = result["widget_shapes"]["PrimaryKeyFilterWidget"]
        self.assertEqual(shape["example"], [42, 7, 13])
        self.assertIn("IN", shape["value_shape"])

    def test_select_by_id_does_not_raise(self):
        """The originally-reported failure: ``fields=['id']`` rejected with
        'has no fields'. It must now resolve and return the pk."""
        folder = Folder.objects.create(name="alpha")
        rows = self._tools().list_rows("filer_folder", fields=["id"])["data"]
        self.assertEqual([r["id"] for r in rows], [folder.pk])

    def test_sort_by_id_descending(self):
        a = Folder.objects.create(name="a")
        b = Folder.objects.create(name="b")
        c = Folder.objects.create(name="c")
        rows = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            sort=[{"field": "id", "dir": "desc"}],
        )["data"]
        self.assertEqual([r["id"] for r in rows], [c.pk, b.pk, a.pk])

    def test_filter_by_id_list_refetches_exact_rows(self):
        a = Folder.objects.create(name="a")
        Folder.objects.create(name="b")
        c = Folder.objects.create(name="c")
        rows = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            filter_data={"id": [a.pk, c.pk]},
        )["data"]
        self.assertEqual({r["id"] for r in rows}, {a.pk, c.pk})

    def test_filter_by_single_id_scalar(self):
        a = Folder.objects.create(name="a")
        Folder.objects.create(name="b")
        rows = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            filter_data={"id": a.pk},
        )["data"]
        self.assertEqual([r["id"] for r in rows], [a.pk])

    def test_wrong_shape_id_filter_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self._tools().list_rows(
                "filer_folder",
                fields=["id"],
                filter_data={"id": {"not": "a pk"}},
            )
        self.assertIn("PrimaryKeyFilterWidget", str(ctx.exception))

    def test_non_numeric_id_rejected_before_query(self):
        """A non-numeric id for an integer pk is rejected up front (clear
        error), not passed to ``id__in`` where the ORM would 500."""
        with self.assertRaises(ValueError) as ctx:
            self._tools().list_rows(
                "filer_folder",
                fields=["id"],
                filter_data={"id": "abc"},
            )
        self.assertIn("abc", str(ctx.exception))


class PrimaryKeyFilterWidgetParseTests(TestCase):
    """The widget reads a single pk or several pks separated by commas,
    whitespace, or semicolons (the text-input UI), plus native scalar /
    list / autocomplete-shaped values (MCP)."""

    def _widget(self):
        from types import SimpleNamespace

        from django_smartbase_admin.engine.filter_widgets import (
            PrimaryKeyFilterWidget,
        )

        widget = PrimaryKeyFilterWidget()
        widget.field = SimpleNamespace(filter_field="id")
        return widget

    def test_separated_string_inputs(self):
        widget = self._widget()
        for raw, expected in [
            ("5", ["5"]),
            ("5,9", ["5", "9"]),
            ("5, 9", ["5", "9"]),
            ("5 9", ["5", "9"]),
            ("5;9", ["5", "9"]),
            ("5\n9", ["5", "9"]),
            (" 5 , 9 ; 13 ", ["5", "9", "13"]),
            ("", []),
        ]:
            self.assertEqual(widget.parse_value_from_input(None, raw), expected, raw)

    def test_native_inputs(self):
        widget = self._widget()
        self.assertEqual(widget.parse_value_from_input(None, 5), [5])
        self.assertEqual(widget.parse_value_from_input(None, [5, 9]), [5, 9])

    def test_coerces_and_drops_invalid_for_integer_pk(self):
        widget = self._widget()
        widget.model_field = Folder._meta.pk  # integer AutoField
        # Coerced to int, and "abc" dropped instead of reaching the ORM.
        self.assertEqual(widget.parse_value_from_input(None, "5, abc, 9"), [5, 9])
        self.assertEqual(widget.parse_value_from_input(None, "abc"), [])
        self.assertEqual(widget.parse_value_from_input(None, [5, "9"]), [5, 9])

    def test_non_numeric_pks_are_allowed(self):
        """Non-integer pks pass through; only values that can't be *that* pk
        type are dropped (UUIDField raises ValidationError, not ValueError)."""
        from uuid import UUID

        from django.db.models import CharField, UUIDField

        char = self._widget()
        char.model_field = CharField()
        self.assertEqual(char.parse_value_from_input(None, "abc"), ["abc"])
        self.assertEqual(char.parse_value_from_input(None, "a, b ; c"), ["a", "b", "c"])

        uid = self._widget()
        uid.model_field = UUIDField()
        u = "550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(uid.parse_value_from_input(None, u), [UUID(u)])
        self.assertEqual(uid.parse_value_from_input(None, "not-a-uuid"), [])

    def test_query_is_in_lookup(self):
        widget = self._widget()
        q = widget.get_base_filter_query_for_parsed_value(None, ["5", "9"])
        self.assertEqual(q.children, [("id__in", ["5", "9"])])
        # Invalid input that coerced to nothing → fail closed (match nothing).
        self.assertEqual(
            widget.get_base_filter_query_for_parsed_value(None, []).children,
            [("pk__in", [])],
        )


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class DeclaredPrimaryKeyTests(TestCase):
    """When the admin already declares the pk, nothing is synthesized — the
    author's column (and its own filter widget) is left untouched."""

    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, _PkDeclaredAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def _tools(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user))

    def test_declared_pk_is_not_duplicated(self):
        result = self._tools().list_admins()
        entry = next(e for e in result["admin_views"] if e["view_id"] == "filer_folder")
        names = [f["name"] for f in entry["fields"]]
        self.assertEqual(names, ["id", "name"])  # exactly one "id", no dup

    def test_declared_pk_select_and_sort_still_work(self):
        a = Folder.objects.create(name="a")
        b = Folder.objects.create(name="b")
        rows = self._tools().list_rows(
            "filer_folder",
            fields=["id", "name"],
            sort=[{"field": "id", "dir": "desc"}],
        )["data"]
        self.assertEqual([r["id"] for r in rows], [b.pk, a.pk])


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class PrimaryKeyAliasTests(TestCase):
    """The synthetic pk column is skipped only when a declared column already
    *is* the pk — not merely because a column's ``filter_field`` points at it."""

    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def _fields(self, admin_class):
        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, admin_class)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None
        user = MagicMock(is_authenticated=True, is_superuser=True)
        result = SBAdminTools(request=build_mcp_request(user)).list_admins()
        entry = next(e for e in result["admin_views"] if e["view_id"] == "filer_folder")
        return {f["name"]: f for f in entry["fields"]}

    def test_explicit_filter_field_alias_suppresses_synthetic(self):
        # ``public_id`` already addresses the pk (filter_field="id"), so no
        # redundant synthetic "id" is added.
        fields = self._fields(_PkAliasFilterFieldAdmin)
        self.assertEqual(list(fields), ["public_id", "name"])  # no synthetic "id"

    def test_display_method_ordering_suppresses_synthetic(self):
        # ``id_label`` orders on the pk → addresses it; no synthetic "id".
        fields = self._fields(_PkMethodOrderingAdmin)
        self.assertEqual(list(fields), ["id_label", "name"])  # no synthetic "id"


class TabulatorIdColumnNameTests(TestCase):
    """``get_tabulator_columns`` reports the row-id column name from the pk
    column (``model_field.primary_key``); when no column is the pk — e.g. the
    synthetic was skipped for an annotation alias — it falls back to the pk
    field name (only the name; no column is grafted on)."""

    def _id_column_name(self, column_fields, pk_name="id"):
        action = SimpleNamespace(
            column_fields=column_fields,
            get_pk_field=lambda: SimpleNamespace(name=pk_name),
        )
        _, id_column_name = SBAdminListAction.get_tabulator_columns(action)
        return id_column_name

    def test_uses_pk_column_field_when_present(self):
        pk_col = SimpleNamespace(
            model_field=SimpleNamespace(primary_key=True),
            field="id",
            serialize_tabulator=lambda: {"field": "id"},
        )
        self.assertEqual(self._id_column_name([pk_col], pk_name="UNUSED"), "id")

    def test_falls_back_to_pk_name_when_no_pk_column(self):
        # An annotation that addresses the pk has no ``model_field.primary_key``.
        alias = SimpleNamespace(
            model_field=None,
            field="public_id__annotate",
            serialize_tabulator=lambda: {"field": "public_id__annotate"},
        )
        self.assertEqual(self._id_column_name([alias]), "id")


class _SessionAdmin(SBAdmin):
    """A model whose pk is a non-``id`` CharField (``session_key``)."""

    model = Session
    sbadmin_list_display = ("expire_date",)


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class CustomPkIdAliasTests(TestCase):
    """For a model whose pk isn't named ``id``, ``"id"`` is accepted as an
    alias on input — so the documented exact-row refetch works even though the
    column is registered under the real pk name."""

    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Session, None)
        sb_admin_site.register(Session, _SessionAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Session, None)
        if self._original is not None:
            sb_admin_site._registry[Session] = self._original
        super().tearDown()

    def _tools(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user))

    def _view_id(self, tools):
        result = tools.list_admins()
        return next(
            e["view_id"] for e in result["admin_views"] if e["model"] == "Session"
        )

    def test_id_alias_selects_sorts_and_filters_the_real_pk(self):
        Session.objects.create(
            session_key="abc123", session_data="", expire_date=timezone.now()
        )
        tools = self._tools()
        view_id = self._view_id(tools)

        # ``fields=["id"]`` resolves (alias → ``session_key``); row mirrors it.
        rows = tools.list_rows(
            view_id, fields=["id"], sort=[{"field": "id", "dir": "asc"}]
        )["data"]
        self.assertEqual([r["id"] for r in rows], ["abc123"])

        # ``filter_data={"id": ...}`` refetches the exact row.
        filtered = tools.list_rows(
            view_id, fields=["id"], filter_data={"id": "abc123"}
        )["data"]
        self.assertEqual([r["id"] for r in filtered], ["abc123"])
