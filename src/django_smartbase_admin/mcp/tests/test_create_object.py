"""Tests for ``SBAdminTools.create_object``.

Drives the tool against the same ``Folder`` admin the update path uses,
so the add flow can be checked against the same fixtures. Each
assertion verifies a single contract — fresh row returns the new pk,
validation failures surface structured errors with no DB write,
inline ops only accept creates.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.audit.models import AdminAuditLog
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)


class CreateFolderAdmin(SBAdmin):
    model = Folder
    fieldsets = ((None, {"fields": ("name", "parent")}),)


class FolderPermissionInline(SBAdminTableInline):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0


class CreateFolderWithInlineAdmin(CreateFolderAdmin):
    inlines = [FolderPermissionInline]


# Pre-register so ``sb_admin_site.urls`` includes the change URL the
# add-flow redirect reverses on success.
sb_admin_site._registry.pop(Folder, None)
sb_admin_site.register(Folder, CreateFolderAdmin)

urlpatterns = [
    path("sb-admin/", sb_admin_site.urls),
    path("admin/", django_admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _CreateObjectTestBase(TestCase):
    admin_class: type[SBAdmin] = CreateFolderAdmin

    @classmethod
    def setUpTestData(cls):
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        SBAdminThreadLocalService.clear_request()
        super().setUpTestData()
        cls.write_user = get_user_model().objects.create(
            username="creator", is_active=True, is_superuser=True, is_staff=True
        )

    def setUp(self):
        super().setUp()
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

    def _create(self, *, field_values=None, inlines=None, user=None):
        user = user or self.write_user
        return SBAdminTools(request=build_mcp_request(user)).create_object(
            "filer_folder",
            field_values=field_values,
            inlines=inlines,
        )


class CreateObjectFieldTests(_CreateObjectTestBase):
    def test_scalar_create_persists_returns_new_pk_and_tags_audit(self):
        """Happy path — new pk, fresh-state payload, FK envelope, audit tag."""
        before_pks = set(Folder.objects.values_list("pk", flat=True))
        parent = Folder.objects.create(name="parent")

        result = self._create(
            field_values={
                "name": "fresh",
                # ``fetch_detail``-shaped envelope must round-trip as
                # the raw pk for the form widget.
                "parent": {"value": parent.pk, "label": str(parent)},
            }
        )

        self.assertEqual(result["status"], "ok")
        new_pk = result["id"]
        self.assertNotIn(new_pk, before_pks)
        self.assertEqual(result["fields"]["name"]["value"], "fresh")

        new_folder = Folder.objects.get(pk=new_pk)
        self.assertEqual(new_folder.name, "fresh")
        self.assertEqual(new_folder.parent_id, parent.pk)

        # MCP bridge tags every audit row from this call.
        folder_ct = ContentType.objects.get_for_model(Folder)
        create_log = AdminAuditLog.objects.get(
            content_type=folder_ct,
            object_id=str(new_pk),
            action_type="create",
        )
        self.assertEqual(create_log.source, "mcp")

    def test_invalid_input_does_not_write(self):
        """Validation failure → ``invalid`` envelope, no row created.

        Covers both Django form errors and our pre-flight ``LookupError``
        gates (unknown field name).
        """
        before_count = Folder.objects.count()

        bad_field = self._create(field_values={"name": ""})
        self.assertEqual(bad_field["status"], "invalid")
        self.assertIn("name", bad_field["errors"]["fields"])

        with self.assertRaises(LookupError):
            self._create(field_values={"bogus": "x"})

        self.assertEqual(Folder.objects.count(), before_count)

    def test_no_add_permission_raises_permission_error(self):
        MCPToolTestConfig.view_permission_for = {"view"}
        try:
            denied_user = MagicMock(is_authenticated=True, is_superuser=False)
            with self.assertRaises((PermissionError, PermissionDenied)):
                self._create(field_values={"name": "x"}, user=denied_user)
        finally:
            MCPToolTestConfig.view_permission_for = None


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class CreateObjectInlineTests(_CreateObjectTestBase):
    admin_class = CreateFolderWithInlineAdmin

    def test_create_with_new_inline_rows(self):
        result = self._create(
            field_values={"name": "withperms"},
            inlines={
                "FolderPermissionInline": [
                    # ``type=1`` + ``everybody=True`` satisfies the
                    # model's ``clean`` rules so the row validates.
                    {"type": 1, "everybody": True, "can_read": 1},
                    {"type": 1, "everybody": True, "can_read": 0},
                ]
            },
        )
        self.assertEqual(result["status"], "ok", msg=result.get("errors"))
        folder = Folder.objects.get(pk=result["id"])
        perms = FolderPermission.objects.filter(folder=folder)
        self.assertEqual(perms.count(), 2)
        self.assertSetEqual({p.can_read for p in perms}, {0, 1})

    def test_rejected_inline_shapes(self):
        """``id`` / ``_delete`` ops and unknown inline names all 404."""
        cases = [
            {"FolderPermissionInline": [{"id": 1, "type": 1, "everybody": True}]},
            {"FolderPermissionInline": [{"_delete": True}]},
            {"DoesNotExistInline": [{"foo": "bar"}]},
        ]
        for inlines in cases:
            with self.subTest(inlines=inlines):
                with self.assertRaises(LookupError):
                    self._create(field_values={"name": "x"}, inlines=inlines)

    def test_empty_new_inline_row_is_rejected_not_dropped(self):
        """A new inline row with no usable value would be a blank extra form
        that Django's formset silently skips — the tool rejects it so the
        create can't 'succeed' with the requested row missing."""
        for op in ({}, {"type": "", "everybody": "", "can_read": ""}):
            with self.subTest(op=op):
                with self.assertRaises(ValueError):
                    self._create(
                        field_values={"name": "x"},
                        inlines={"FolderPermissionInline": [op]},
                    )
