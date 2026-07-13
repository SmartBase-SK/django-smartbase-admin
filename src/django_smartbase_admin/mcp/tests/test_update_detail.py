"""Tests for ``SBAdminTools.update_detail``.

Drives the tool against the same ``Folder`` admin used by the
``fetch_detail`` tests so the write path can be checked against the
fixtures the read path already covers. Each assertion verifies a
single contract — value updates round-trip, validation failures
surface structured errors, inline ops cover update/delete/create.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)


class UpdateFolderAdmin(SBAdmin):
    model = Folder
    fieldsets = ((None, {"fields": ("name", "parent")}),)


class UpdateFolderReadonlyAdmin(SBAdmin):
    model = Folder
    fieldsets = ((None, {"fields": ("name", "uploaded_at")}),)
    readonly_fields = ("uploaded_at",)


class FolderPermissionInline(SBAdminTableInline):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0


class UpdateFolderWithInlineAdmin(UpdateFolderAdmin):
    inlines = [FolderPermissionInline]


# Pre-register so ``sb_admin_site.urls`` includes
# ``filer_folder_change`` / ``filer_folder_changelist`` when the
# URLconf is loaded — ``ModelAdmin._response_post_save`` reverses
# those on a successful save and ``setUp`` would otherwise patch the
# registry too late.
sb_admin_site._registry.pop(Folder, None)
sb_admin_site.register(Folder, UpdateFolderAdmin)

urlpatterns = [
    path("sb-admin/", sb_admin_site.urls),
    path("admin/", django_admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _UpdateDetailTestBase(TestCase):
    admin_class: type[SBAdmin] = UpdateFolderAdmin

    @classmethod
    def setUpTestData(cls):
        # MCP tests bind ``SBAdminThreadLocalService`` via the bridge;
        # the contextvar can survive between class-level fixtures and
        # would leak a stale request into ``Folder.objects.create``
        # auditing below (FK to a rolled-back user).
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        SBAdminThreadLocalService.clear_request()
        super().setUpTestData()
        cls.write_user = get_user_model().objects.create(
            username="writer", is_active=True, is_superuser=True, is_staff=True
        )

    def setUp(self):
        super().setUp()
        # Reset the SBAdmin thread-local between tests — the MCP bridge
        # binds it and we don't want a prior test's request leaking into
        # the next class's ``setUpTestData`` (audit hooks would then
        # write with a stale user FK).
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

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

    def _update(self, object_id, *, main_values=None, component_values=None, user=None):
        # ``_changeform_view`` writes an ``admin.LogEntry`` on save and
        # the row's ``user`` FK must point at a real auth row; a
        # ``MagicMock`` would round-trip its mock pk through the insert.
        user = user or self.write_user
        component_values = {"main": main_values or {}, **(component_values or {})}
        return SBAdminTools(request=build_mcp_request(user)).update_detail(
            "filer_folder",
            str(object_id),
            component_values=component_values,
        )


class UpdateDetailFieldTests(_UpdateDetailTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.parent = Folder.objects.create(name="parent")
        cls.child = Folder.objects.create(name="child", parent=cls.parent)

    def test_scalar_update_persists_and_returns_fresh_state(self):
        from django.contrib.contenttypes.models import ContentType

        from django_smartbase_admin.audit.models import AdminAuditLog

        result = self._update(self.child.pk, main_values={"name": "renamed"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id"], self.child.pk)
        self.assertEqual(
            result["components"]["main"]["fields"]["name"]["value"],
            "renamed",
        )
        self.assertEqual(Folder.objects.get(pk=self.child.pk).name, "renamed")

        # MCP bridge tags the active request — every audit row from this
        # call inherits ``source="mcp"`` automatically, including ORM
        # saves and any manual ``create_audit_log`` from custom actions.
        folder_ct = ContentType.objects.get_for_model(Folder)
        update_log = AdminAuditLog.objects.get(
            content_type=folder_ct,
            object_id=str(self.child.pk),
            action_type="update",
        )
        self.assertEqual(update_log.source, "mcp")

    def test_fk_update_accepts_value_label_envelope(self):
        """Agents echo ``fetch_detail`` payloads back; raw pk works too."""
        other = Folder.objects.create(name="other")
        result = self._update(
            self.child.pk,
            main_values={"parent": {"value": other.pk, "label": str(other)}},
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(Folder.objects.get(pk=self.child.pk).parent_id, other.pk)

    def test_untouched_fields_keep_their_values(self):
        """Sparse main component values must preserve unspecified columns."""
        self._update(self.child.pk, main_values={"name": "renamed"})
        # ``parent`` was not in the main component values, so it should still point
        # at the original parent rather than being cleared.
        self.assertEqual(Folder.objects.get(pk=self.child.pk).parent_id, self.parent.pk)

    def test_blank_required_field_returns_invalid_with_errors(self):
        result = self._update(self.child.pk, main_values={"name": ""})

        self.assertEqual(result["status"], "invalid")
        main_errors = result["errors"]["components"]["main"]
        self.assertEqual(main_errors["type"], "form")
        self.assertEqual(main_errors["fields"]["name"][0]["code"], "required")
        # No DB write on validation failure.
        self.assertEqual(Folder.objects.get(pk=self.child.pk).name, "child")

    def test_unknown_field_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self._update(self.child.pk, main_values={"bogus": "x"})

    def test_missing_object_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self._update(99999, main_values={"name": "x"})

    def test_no_change_permission_raises_permission_error(self):
        MCPToolTestConfig.view_permission_for = {"view"}
        try:
            denied_user = MagicMock(is_authenticated=True, is_superuser=False)
            with self.assertRaises((PermissionError, PermissionDenied)):
                self._update(
                    self.child.pk,
                    main_values={"name": "x"},
                    user=denied_user,
                )
        finally:
            MCPToolTestConfig.view_permission_for = None


class UpdateDetailReadonlyFieldTests(_UpdateDetailTestBase):
    admin_class = UpdateFolderReadonlyAdmin

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.folder = Folder.objects.create(name="folder")

    def test_readonly_field_raises_lookup_error(self):
        original = Folder.objects.get(pk=self.folder.pk).uploaded_at
        with self.assertRaises(LookupError) as ctx:
            self._update(
                self.folder.pk,
                main_values={"uploaded_at": "2099-01-01T00:00:00"},
            )
        self.assertIn("uploaded_at", str(ctx.exception))
        self.assertEqual(Folder.objects.get(pk=self.folder.pk).uploaded_at, original)


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class UpdateDetailInlineTests(_UpdateDetailTestBase):
    admin_class = UpdateFolderWithInlineAdmin

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.folder = Folder.objects.create(name="folder")
        # ``type=1`` ("this item only") + ``everybody=True`` satisfies
        # ``FolderPermission.clean``; the default ``type=0`` ("all items")
        # conflicts with a non-null folder FK and would trip validation
        # the first time we round-trip the row through ``full_clean``.
        cls.perm_a = FolderPermission.objects.create(
            folder=cls.folder, type=1, everybody=True
        )
        cls.perm_b = FolderPermission.objects.create(
            folder=cls.folder, type=1, everybody=True
        )

    def test_update_existing_inline_row(self):
        # ``can_read`` is a tri-state SmallIntegerField on filer
        # ``FolderPermission`` (``None`` = inherit, 1 = allow, 0 = deny).
        result = self._update(
            self.folder.pk,
            component_values={
                "FolderPermissionInline": [
                    {"id": self.perm_a.pk, "can_read": 1},
                ]
            },
        )
        self.assertEqual(result["status"], "ok", msg=result.get("errors"))
        self.perm_a.refresh_from_db()
        self.assertEqual(self.perm_a.can_read, 1)
        # Untouched sibling row keeps its (None) value.
        self.perm_b.refresh_from_db()
        self.assertIsNone(self.perm_b.can_read)

    def test_delete_existing_inline_row(self):
        result = self._update(
            self.folder.pk,
            component_values={
                "FolderPermissionInline": [
                    {"id": self.perm_a.pk, "_delete": True},
                ]
            },
        )
        self.assertEqual(result["status"], "ok", msg=result.get("errors"))
        self.assertFalse(FolderPermission.objects.filter(pk=self.perm_a.pk).exists())
        # Sibling row is preserved.
        self.assertTrue(FolderPermission.objects.filter(pk=self.perm_b.pk).exists())

    def test_create_new_inline_row(self):
        result = self._update(
            self.folder.pk,
            component_values={
                "FolderPermissionInline": [
                    # type=1 + everybody=True satisfies the model's
                    # ``clean`` rules; the parent folder FK is wired
                    # in by ``BaseInlineFormSet`` automatically.
                    {"type": 1, "everybody": True, "can_read": 1},
                ]
            },
        )
        self.assertEqual(result["status"], "ok", msg=result.get("errors"))
        new_rows = FolderPermission.objects.filter(folder=self.folder, can_read=1)
        self.assertEqual(new_rows.count(), 1)

    def test_unknown_inline_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self._update(
                self.folder.pk,
                component_values={"DoesNotExistInline": []},
            )

    def test_unknown_inline_row_id_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self._update(
                self.folder.pk,
                component_values={
                    "FolderPermissionInline": [
                        {"id": 99999, "everybody": True},
                    ]
                },
            )

    def test_duplicate_inline_row_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate row id"):
            self._update(
                self.folder.pk,
                component_values={
                    "FolderPermissionInline": [
                        {"id": self.perm_a.pk, "can_read": 1},
                        {"id": self.perm_a.pk, "can_read": 0},
                    ]
                },
            )

    def test_existing_inline_validation_error_includes_row_id(self):
        result = self._update(
            self.folder.pk,
            component_values={
                "FolderPermissionInline": [
                    {"id": self.perm_a.pk, "type": 0},
                ]
            },
        )

        self.assertEqual(result["status"], "invalid")
        component_errors = result["errors"]["components"]["FolderPermissionInline"]
        self.assertEqual(component_errors["type"], "formset")
        row_errors = component_errors["rows"][0]
        self.assertEqual(row_errors["id"], self.perm_a.pk)
        self.assertIsInstance(row_errors["index"], int)
        self.assertTrue(row_errors["non_field"] or row_errors["fields"])
