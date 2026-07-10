"""Tests for ``SBAdminTools.fetch_add_form``.

Verifies the add-form blueprint mirrors ``fetch_detail`` minus ``id``:
same field metadata shape, ``widget_id`` exposed for autocomplete
fields, inline blocks present with empty rows.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import path
from django.utils.safestring import mark_safe
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class FolderPermissionInline(SBAdminTableInline):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0


class FolderAddFormTestAdmin(SBAdmin):
    model = Folder
    fieldsets = ((None, {"fields": ("name", "parent")}),)
    inlines = [FolderPermissionInline]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchAddFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        SBAdminThreadLocalService.clear_request()

    def setUp(self):
        super().setUp()
        SBAdminThreadLocalService.clear_request()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderAddFormTestAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def _fetch(self, *, user=None, fields=None):
        user = user or MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user)).fetch_add_form(
            "filer_folder", fields=fields
        )

    def test_blueprint_shape_and_autocomplete_widget_id(self):
        """No ``id``, full field metadata, empty inline rows, and the
        autocomplete-backed ``parent`` field exposes ``widget_id`` so the
        agent can wire ``autocomplete`` calls before ``create_object``."""
        result = self._fetch()

        self.assertNotIn("id", result)
        self.assertEqual(set(result), {"fields", "inlines"})
        self.assertEqual(list(result["fields"]), ["name", "parent"])

        name = result["fields"]["name"]
        self.assertFalse(name["readonly"])
        self.assertTrue(name["required"])
        self.assertIsNotNone(name["widget"])

        parent = result["fields"]["parent"]
        self.assertFalse(parent["readonly"])
        self.assertIsNotNone(parent["widget"])
        # Autocomplete-backed FK must carry widget_id for the
        # autocomplete tool to dispatch against.
        self.assertIn("widget_id", parent)

        inline = result["inlines"]["FolderPermissionInline"]
        self.assertEqual(inline["rows"], [])
        self.assertFalse(inline["truncated"])
        self.assertEqual(
            list(inline["row_schema"]["fields"]),
            ["type", "everybody", "can_read"],
        )
        self.assertTrue(inline["row_schema"]["fields"]["type"]["required"])

    def test_field_subset_and_unknown_field_raises(self):
        result = self._fetch(fields=["name"])
        self.assertEqual(list(result["fields"]), ["name"])

        with self.assertRaises(LookupError):
            self._fetch(fields=["bogus"])

    def test_no_add_permission_raises(self):
        denied = MagicMock(is_authenticated=True, is_superuser=False)
        MCPToolTestConfig.view_permission_for = set()
        with self.assertRaises((PermissionError, PermissionDenied)):
            self._fetch(user=denied)


class FolderReadonlyAddFormTestAdmin(SBAdmin):
    """Admin exposing a readonly display *method* on its form.

    The method reads the instance, so on the add page (no instance) the
    readonly-value extraction is asked for a value with ``obj=None``.
    """

    model = Folder
    readonly_fields = ("computed_summary",)
    fieldsets = ((None, {"fields": ("name", "computed_summary")}),)

    def computed_summary(self, obj):
        if not obj or not obj.pk:
            return "—"
        return mark_safe(f"<span>{obj.name}</span>")

    computed_summary.short_description = "Summary"


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchAddFormReadonlyFieldTests(TestCase):
    """Regression: a readonly method field on the add page must not crash.

    Django's ``lookup_field`` dereferences ``obj._meta`` on its first line;
    on the add page ``obj`` is ``None``. The readonly-value extraction has
    to short-circuit and report an empty value rather than 500.
    """

    def setUp(self):
        super().setUp()
        SBAdminThreadLocalService.clear_request()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderReadonlyAddFormTestAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def test_readonly_method_field_is_empty_not_crash(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        # Must not raise (previously: AttributeError 'NoneType'.. ._meta).
        result = SBAdminTools(request=build_mcp_request(user)).fetch_add_form(
            "filer_folder"
        )

        summary = result["fields"]["computed_summary"]
        self.assertTrue(summary["readonly"])
        # Add page has no instance, so the computed readonly value is empty.
        self.assertIsNone(summary["value"])
        # The writable field is still present and editable.
        self.assertFalse(result["fields"]["name"]["readonly"])
