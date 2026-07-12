"""Tests for ``SBAdminTools.fetch_detail`` and the ``detail_fields`` schema.

Drives the tool against a real ``Folder`` admin so the assertions
double as a contract check on the wire shape: top-level ``id`` +
``fields`` + ``inlines``, each field carrying ``value`` / ``readonly``
/ ``required`` / ``widget``, related selections nested as
``{"value", "label"}``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django import forms
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import (
    SBAdmin,
    SBAdminTableInline,
    SBAdminTableInlinePaginated,
)
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.configuration import SBAdminWhoamiConfig
from django_smartbase_admin.engine.actions import sbadmin_action
from django_smartbase_admin.engine.dashboard import SBAdminDashboardListWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class FolderDetailTestAdmin(SBAdmin):
    """Admin with a scalar form field, an FK form field, a readonly
    model field, and a callable readonly method — covers every value
    shape the detail tool produces (scalar, related selection with
    label, readonly scalar, readonly callable)."""

    model = Folder
    fieldsets = ((None, {"fields": ("name", "parent", "uploaded_at", "child_count")}),)
    readonly_fields = ("uploaded_at", "child_count")

    def child_count(self, obj):
        return obj.children.count() if obj else 0


class ChildFolderListWidget(SBAdminDashboardListWidget):
    widget_id = "child_folder_list_widget"
    model = Folder
    list_display = ("id", "name")
    search_fields = ("name",)
    path_to_parent_instance_id = "parent_id"

    @sbadmin_action(mcp_components="get_refresh_form_components")
    def action_refresh_name(self, request, modifier, object_id=None):
        return JsonResponse(
            {
                "object_id": object_id,
                "parent_id": self.get_parent_instance_id(request),
                "row_id": request.POST["row_id"],
                "value": request.POST["value"],
            }
        )

    def get_refresh_form_components(self, request):
        class RefreshNameForm(forms.Form):
            row_id = forms.IntegerField()
            value = forms.CharField(required=False)

        return {"main": RefreshNameForm()}


class FolderDetailWithWidgetAdmin(FolderDetailTestAdmin):
    widgets = [ChildFolderListWidget]
    fieldsets = ((None, {"fields": ("name", ChildFolderListWidget)}),)


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _FetchDetailTestBase(TestCase):
    admin_class: type[SBAdmin] = FolderDetailTestAdmin

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, self.admin_class)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig().mcp_whoami_sbadmin = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig().mcp_whoami_sbadmin = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def _fetch(self, object_id, fields=None, *, user=None):
        user = user or MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user)).fetch_detail(
            "filer_folder",
            str(object_id),
            fields=fields,
        )


class FetchDetailTests(_FetchDetailTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.parent = Folder.objects.create(name="parent")
        cls.child_a = Folder.objects.create(name="child_a", parent=cls.parent)
        cls.child_b = Folder.objects.create(name="child_b", parent=cls.parent)

    def test_returns_values_with_per_field_metadata(self):
        """Covers every value shape: editable scalar, editable FK,
        readonly scalar, readonly callable."""
        row = self._fetch(self.child_a.pk)

        self.assertEqual(row["id"], self.child_a.pk)
        fields = row["components"]["main"]["fields"]
        self.assertEqual(list(fields), ["name", "parent", "uploaded_at", "child_count"])

        # Editable scalar — Folder.name has blank=False.
        self.assertEqual(fields["name"]["value"], "child_a")
        self.assertFalse(fields["name"]["readonly"])
        self.assertTrue(fields["name"]["required"])
        self.assertIsNotNone(fields["name"]["widget"])

        # Editable FK — Folder.parent is nullable.
        self.assertEqual(
            fields["parent"]["value"],
            {"value": self.parent.pk, "label": str(self.parent)},
        )
        self.assertFalse(fields["parent"]["readonly"])
        self.assertFalse(fields["parent"]["required"])
        self.assertIsNotNone(fields["parent"]["widget"])

        # Readonly fields always report required=False, widget=None.
        self.assertEqual(fields["uploaded_at"]["value"], self.child_a.uploaded_at)
        self.assertTrue(fields["uploaded_at"]["readonly"])
        self.assertFalse(fields["uploaded_at"]["required"])
        self.assertIsNone(fields["uploaded_at"]["widget"])

        # Readonly callable result passes through verbatim.
        self.assertEqual(fields["child_count"]["value"], 0)
        self.assertTrue(fields["child_count"]["readonly"])
        self.assertFalse(fields["child_count"]["required"])
        self.assertIsNone(fields["child_count"]["widget"])

        # Root row: null FK must skip label resolution cleanly.
        parent_row = self._fetch(self.parent.pk)
        parent_fields = parent_row["components"]["main"]["fields"]
        self.assertIsNone(parent_fields["parent"]["value"])
        self.assertEqual(parent_fields["child_count"]["value"], 2)

    def test_fetch_whoami_matches_fetch_detail_for_configured_target(self):
        user = MagicMock(
            pk=self.child_a.pk,
            id=self.child_a.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=True,
        )
        MCPToolTestConfig().mcp_whoami_sbadmin = SBAdminWhoamiConfig(
            view_id="filer_folder"
        )
        tools = SBAdminTools(request=build_mcp_request(user))

        profile = tools.fetch_whoami(fields=["name"])
        detail = self._fetch(self.child_a.pk, fields=["name"], user=user)

        self.assertEqual(profile["view_id"], "filer_folder")
        self.assertEqual(profile["object_id"], str(self.child_a.pk))
        self.assertEqual(
            {k: v for k, v in profile.items() if k not in {"view_id", "object_id"}},
            detail,
        )

    def test_fetch_whoami_raises_when_unconfigured(self):
        user = MagicMock(
            pk=self.child_a.pk,
            id=self.child_a.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=True,
        )

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).fetch_whoami()

    def test_fetch_whoami_raises_when_configured_admin_is_missing(self):
        user = MagicMock(
            pk=self.child_a.pk,
            id=self.child_a.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=True,
        )
        MCPToolTestConfig().mcp_whoami_sbadmin = SBAdminWhoamiConfig(
            view_id="missing_profile"
        )

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).fetch_whoami()

    def test_fetch_whoami_raises_permission_error_when_target_denied(self):
        user = MagicMock(
            pk=self.child_a.pk,
            id=self.child_a.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=False,
        )
        MCPToolTestConfig().mcp_whoami_sbadmin = SBAdminWhoamiConfig(
            view_id="filer_folder"
        )
        MCPToolTestConfig.view_permission_for = set()

        with self.assertRaises(PermissionError):
            SBAdminTools(request=build_mcp_request(user)).fetch_whoami()

    def test_field_subset_projection(self):
        row = self._fetch(self.child_a.pk, fields=["name"])
        self.assertEqual(row["id"], self.child_a.pk)
        fields = row["components"]["main"]["fields"]
        self.assertEqual(list(fields), ["name"])
        self.assertEqual(fields["name"]["value"], "child_a")

    def test_error_paths_surface_clear_exceptions(self):
        """Missing object, unknown field, unknown admin, denied admin —
        each raises a distinct exception."""
        with self.assertRaises(LookupError):
            self._fetch(99999)

        with self.assertRaises(LookupError):
            self._fetch(self.parent.pk, fields=["bogus"])

        with self.assertRaises(LookupError):
            SBAdminTools(
                request=build_mcp_request(
                    MagicMock(is_authenticated=True, is_superuser=True)
                )
            ).fetch_detail("does_not_exist", str(self.parent.pk))

        denied_user = MagicMock(is_authenticated=True, is_superuser=False)
        MCPToolTestConfig.view_permission_for = set()
        with self.assertRaises((PermissionError, PermissionDenied)):
            self._fetch(self.parent.pk, user=denied_user)

    def test_restrict_queryset_hides_object(self):
        """A row filtered out by ``restrict_queryset`` is indistinguishable
        from a missing one — the tool must report ``LookupError``."""

        def restrict(qs, model):
            if model is Folder:
                return qs.exclude(pk=self.child_a.pk)
            return qs

        MCPToolTestConfig.restrict_qs = staticmethod(restrict)
        try:
            with self.assertRaises(LookupError):
                self._fetch(self.child_a.pk)
            self._fetch(self.parent.pk)  # sanity: un-filtered still resolves
        finally:
            MCPToolTestConfig.restrict_qs = None


class FetchDetailWidgetTests(_FetchDetailTestBase):
    admin_class = FolderDetailWithWidgetAdmin

    @classmethod
    def setUpTestData(cls):
        cls.parent = Folder.objects.create(name="parent")
        cls.child_a = Folder.objects.create(name="child_a", parent=cls.parent)
        cls.child_b = Folder.objects.create(name="child_b", parent=cls.parent)
        cls.other_parent = Folder.objects.create(name="other_parent")
        cls.other_child = Folder.objects.create(
            name="other_child", parent=cls.other_parent
        )

    def setUp(self):
        super().setUp()
        MCPToolTestConfig().init_configuration_static()

    def test_detail_surfaces_parent_scoped_list_widget(self):
        result = self._fetch(self.parent.pk)

        self.assertEqual(list(result["components"]["main"]["fields"]), ["name"])
        widget = result["widgets"][0]
        self.assertEqual(widget["view_id"], "filer_folder_child_folder_list_widget")
        self.assertEqual(widget["parent_view_id"], "filer_folder")
        self.assertEqual(widget["parent_object_id"], str(self.parent.pk))
        self.assertTrue(widget["requires_parent_object_id"])
        self.assertEqual(widget["data_tool"], "list_rows")
        self.assertEqual([field["name"] for field in widget["fields"]], ["id", "name"])
        self.assertEqual(widget["search_fields"], ["name"])
        self.assertEqual(
            widget["mcp_actions"],
            [
                {
                    "action_id": "action_refresh_name",
                    "kind": "method",
                    "components": {
                        "main": {
                            "type": "form",
                            "fields": {
                                "row_id": {
                                    "value": None,
                                    "required": True,
                                    "widget": "NumberInput",
                                    "readonly": False,
                                    "label": "row_id",
                                },
                                "value": {
                                    "value": None,
                                    "required": False,
                                    "widget": "TextInput",
                                    "readonly": False,
                                    "label": "value",
                                },
                            },
                        },
                    },
                }
            ],
        )

    def test_list_rows_can_read_parent_scoped_widget_rows(self):
        detail = self._fetch(self.parent.pk)
        widget = detail["widgets"][0]

        request = build_mcp_request(MagicMock(is_authenticated=True, is_superuser=True))
        rows = SBAdminTools(request=request).list_rows(
            widget["view_id"],
            fields=["id", "name"],
            parent_object_id=widget["parent_object_id"],
            page_size=10,
        )["data"]

        self.assertEqual({row["name"] for row in rows}, {"child_a", "child_b"})
        self.assertNotIn("other_child", {row["name"] for row in rows})

    def test_invoke_action_binds_parent_scoped_widget_context(self):
        widget = self._fetch(self.parent.pk)["widgets"][0]
        request = build_mcp_request(MagicMock(is_authenticated=True, is_superuser=True))

        result = SBAdminTools(request=request).invoke_action(
            widget["view_id"],
            "action_refresh_name",
            object_id=widget["parent_object_id"],
            component_values={"main": {"row_id": self.child_a.pk, "value": "updated"}},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["object_id"], str(self.parent.pk))
        self.assertEqual(result["parent_id"], str(self.parent.pk))
        self.assertEqual(result["row_id"], str(self.child_a.pk))
        self.assertEqual(result["value"], "updated")

    def test_list_rows_requires_parent_for_parent_scoped_widget(self):
        request = build_mcp_request(MagicMock(is_authenticated=True, is_superuser=True))

        with self.assertRaises(ValueError):
            SBAdminTools(request=request).list_rows(
                "filer_folder_child_folder_list_widget",
                fields=["id", "name"],
                page_size=10,
            )

    def test_fetch_widget_data_rejects_non_widget_view(self):
        request = build_mcp_request(MagicMock(is_authenticated=True, is_superuser=True))

        with self.assertRaises(LookupError):
            SBAdminTools(request=request).fetch_widget_data("filer_folder")


class FolderPermissionInline(SBAdminTableInline):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0


class FolderPermissionPaginatedInline(SBAdminTableInlinePaginated):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0
    per_page = 2


class FolderDetailWithInlineAdmin(FolderDetailTestAdmin):
    inlines = [FolderPermissionInline]


class FolderDetailWithPaginatedInlineAdmin(FolderDetailTestAdmin):
    inlines = [FolderPermissionPaginatedInline]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchDetailInlinesTests(_FetchDetailTestBase):
    """Inlines are auto-hydrated with full per-field metadata; no
    per-call inline / field projection."""

    admin_class = FolderDetailWithInlineAdmin

    @classmethod
    def setUpTestData(cls):
        cls.folder = Folder.objects.create(name="folder")
        cls.perms = [
            FolderPermission.objects.create(folder=cls.folder, everybody=bool(i % 2))
            for i in range(5)
        ]

    def test_inlines_auto_hydrate_with_per_field_metadata(self):
        result = self._fetch(self.folder.pk, fields=["name"])

        self.assertEqual(set(result), {"id", "components", "widgets"})
        inline = result["components"]["FolderPermissionInline"]
        self.assertEqual(inline["type"], "formset")
        self.assertFalse(inline["truncated"])
        self.assertIn("type", inline["fields"])
        self.assertEqual(len(inline["rows"]), 5)

        row = inline["rows"][0]
        self.assertEqual(set(row), {"id", "fields"})
        self.assertEqual(set(row["fields"]), {"type", "everybody", "can_read"})
        self.assertEqual(row["fields"]["everybody"]["readonly"], False)
        self.assertIsNotNone(row["fields"]["everybody"]["widget"])
        self.assertIn("required", row["fields"]["everybody"])

    def test_empty_inlines_block_present(self):
        """Admin without inlines still emits ``inlines: {}`` so the
        wire shape is uniform across admins."""

        class NoInlineAdmin(FolderDetailTestAdmin):
            inlines = []

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, NoInlineAdmin)
        MCPToolTestConfig().init_view_map()
        try:
            result = self._fetch(self.folder.pk, fields=["name"])
        finally:
            sb_admin_site._registry.pop(Folder, None)
            sb_admin_site.register(Folder, self.admin_class)
            MCPToolTestConfig().init_view_map()

        self.assertEqual(set(result["components"]), {"main"})


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchDetailPaginatedInlineTests(_FetchDetailTestBase):
    """Paginated inlines cap at ``per_page`` and flag ``truncated``."""

    admin_class = FolderDetailWithPaginatedInlineAdmin

    @classmethod
    def setUpTestData(cls):
        cls.folder = Folder.objects.create(name="folder")
        cls.perms = [
            FolderPermission.objects.create(folder=cls.folder, everybody=bool(i % 2))
            for i in range(5)
        ]

    def test_paginated_inline_truncates_with_flag(self):
        result = self._fetch(self.folder.pk, fields=["name"])
        inline = result["components"]["FolderPermissionPaginatedInline"]
        # FolderPermissionPaginatedInline.per_page = 2 against 5 rows.
        self.assertEqual(len(inline["rows"]), 2)
        self.assertTrue(inline["truncated"])


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class DetailFieldsSchemaTests(_FetchDetailTestBase):
    def test_list_admins_advertises_detail_field_names_only(self):
        """``list_admins.detail_fields`` lists names only — per-field
        metadata ships with the values from ``fetch_detail``."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        result = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]

        entry = next(e for e in result if e["view_id"] == "filer_folder")
        self.assertEqual(
            entry["detail_fields"],
            ["name", "parent", "uploaded_at", "child_count"],
            "detail_fields must be a flat name list in fieldset order",
        )


class FolderHtmlDisplayAdmin(SBAdmin):
    """Admin whose readonly callable returns ``mark_safe`` HTML — the
    ``*_display`` pattern that, unsanitized, leaks inline CSS / JS into
    ``fetch_detail``. Covers the sanitize contract end to end."""

    model = Folder
    fieldsets = ((None, {"fields": ("name", "rich")}),)
    readonly_fields = ("rich",)

    def rich(self, obj):
        from django.utils.safestring import mark_safe

        return mark_safe(
            '<div class="wrap" style="color:red" onclick="x()">'
            "<style>.wrap{color:red}</style>"
            "<script>steal()</script>"
            '<span style="font-weight:bold">flag_a</span>'
            '<a href="/ticketing/queue/53/change/" class="lnk">Queue 53</a>'
            "<table><tr><td>Max</td><td>3</td></tr></table>"
            "</div>"
        )


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchDetailHtmlSanitizeTests(_FetchDetailTestBase):
    admin_class = FolderHtmlDisplayAdmin

    @classmethod
    def setUpTestData(cls):
        cls.folder = Folder.objects.create(name="f")

    def test_display_html_is_sanitized_keeping_structure(self):
        """One pass over the sanitize contract: structure + ``href`` kept,
        presentational/executable noise gone."""
        value = self._fetch(self.folder.pk)["components"]["main"]["fields"]["rich"][
            "value"
        ]

        # Structure preserved — div/span/table/link tags survive.
        self.assertIn("<table>", value)
        self.assertIn("<td>Max</td>", value)
        self.assertIn("<span>flag_a</span>", value)
        self.assertIn("<div>", value)
        # Information-bearing attribute kept.
        self.assertIn('href="/ticketing/queue/53/change/"', value)

        # Presentational / executable noise stripped.
        self.assertNotIn("style=", value)
        self.assertNotIn("class=", value)
        self.assertNotIn("onclick", value)
        # script / style content removed entirely, not just unwrapped.
        self.assertNotIn("steal()", value)
        self.assertNotIn(".wrap{color:red}", value)
        self.assertNotIn("<script", value)
        self.assertNotIn("<style", value)
