"""End-to-end coverage for fake inlines on the MCP surface.

Two concerns, one test class each:

* ``SafeFakeInlineTests`` — a well-configured ``SBAdminFakeInlineMixin``
  surfaces in ``list_admins`` (with ``join_kind="fake"``) and hydrates in
  ``list_rows(include_inlines=...)`` exactly like a regular inline.

* ``UnsafeFakeInlineTests`` — when the per-parent / batch filter overrides
  are asymmetric (``sbadmin.W004``), the inline is hidden from
  ``list_admins`` AND silently skipped during ``list_rows`` hydration if an
  agent bypasses the schema. Both halves checked in one test — they're the
  two sides of the same safety mechanism, and either failing alone tells
  us the asymmetric-override guard regressed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.fake_inline import SBAdminFakeInlineMixin
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class FolderPermissionFakeInline(SBAdminFakeInlineMixin, SBAdminTableInline):
    """Reach ``FolderPermission`` through the fake-inline mixin even though a
    real ``folder`` FK exists — exercises the mixin's path, not Django's."""

    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0
    can_delete = False
    max_num = 0
    path_to_parent_instance_id = "folder_id"

    def get_fake_inline_identifier_annotate(self):
        return F("folder_id")


class UnsafeFolderPermissionFakeInline(FolderPermissionFakeInline):
    """Asymmetric override — per-parent customized, batch left at default.

    This is exactly the ``sbadmin.W004`` footgun: the change form would use
    the customized join logic, the batch reader would not, and they'd
    silently disagree.
    """

    def filter_fake_inline_identifier_by_parent_instance(self, qs, parent_instance):
        return qs.filter(folder_id=parent_instance.pk)


class FolderFakeInlineTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name")
    sbadmin_fake_inlines = [FolderPermissionFakeInline]


class FolderUnsafeFakeInlineTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name")
    sbadmin_fake_inlines = [UnsafeFolderPermissionFakeInline]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _FakeInlineTestBase(TestCase):
    admin_class: type[SBAdmin] = FolderFakeInlineTestAdmin

    def setUp(self):
        super().setUp()
        SBAdminThreadLocalService.clear_request()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, self.admin_class)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()


class SafeFakeInlineTests(_FakeInlineTestBase):
    admin_class = FolderFakeInlineTestAdmin

    @classmethod
    def setUpTestData(cls):
        SBAdminThreadLocalService.clear_request()
        cls.alpha = Folder.objects.create(name="alpha_fake")
        cls.lonely = Folder.objects.create(name="lonely_fake")
        FolderPermission.objects.create(folder=cls.alpha, everybody=True)
        FolderPermission.objects.create(folder=cls.alpha, everybody=False)

    def test_schema_lists_fake_inline_and_list_rows_hydrates(self):
        """One pass: ``list_admins`` advertises the fake inline with the right
        ``join_kind``, then ``list_rows(include_inlines=...)`` hydrates its
        rows next to the parent — covering both halves of the wire contract.
        """
        user = MagicMock(is_authenticated=True, is_superuser=True)

        admins = SBAdminTools(request=build_mcp_request(user)).list_admins()
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        inline_names = {entry["inline_name"]: entry for entry in folder["inlines"]}
        self.assertIn("FolderPermissionFakeInline", inline_names)
        # Fake inlines report ``"fk"`` over the wire — the distinction is
        # an internal implementation detail and the agent contract for
        # batch reads is identical to a real FK.
        entry = inline_names["FolderPermissionFakeInline"]
        self.assertEqual(entry["join_kind"], "fk")
        # ``model`` reports the *original* model, not the dynamic proxy.
        self.assertEqual(entry["model"], "filer.FolderPermission")

        result = SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder",
            fields=["name"],
            include_inlines=[
                {
                    "inline_name": "FolderPermissionFakeInline",
                    "fields": ["everybody"],
                }
            ],
        )
        by_name = {row["name"]: row for row in result["data"]}
        self.assertEqual(
            len(by_name["alpha_fake"]["_inlines"]["FolderPermissionFakeInline"]), 2
        )
        self.assertNotIn("_inlines", by_name["lonely_fake"])


class UnsafeFakeInlineTests(_FakeInlineTestBase):
    admin_class = FolderUnsafeFakeInlineTestAdmin

    @classmethod
    def setUpTestData(cls):
        SBAdminThreadLocalService.clear_request()
        cls.alpha = Folder.objects.create(name="alpha_unsafe")
        FolderPermission.objects.create(folder=cls.alpha, everybody=True)

    def test_unsafe_fake_inline_is_hidden_and_skipped(self):
        """Both halves of the W004 safety mechanism in one pass: the
        unsafe handle is absent from ``list_admins`` (so the agent never
        learns it), AND if an agent bypasses the schema and supplies it
        anyway, ``list_rows`` silently drops it (logged, no exception, no
        ``_inlines`` attached).
        """
        user = MagicMock(is_authenticated=True, is_superuser=True)

        admins = SBAdminTools(request=build_mcp_request(user)).list_admins()
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        self.assertNotIn(
            "UnsafeFolderPermissionFakeInline",
            {entry["inline_name"] for entry in folder["inlines"]},
        )

        result = SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder",
            fields=["name"],
            include_inlines=[
                {
                    "inline_name": "UnsafeFolderPermissionFakeInline",
                    "fields": ["everybody"],
                }
            ],
        )
        for row in result["data"]:
            self.assertNotIn("_inlines", row)
