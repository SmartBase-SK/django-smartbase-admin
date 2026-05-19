"""Tests for ``SBAdminInline.get_data_for_parents`` via the MCP wiring
``list_rows(include_inlines=...)``.

Two test classes — one per admin shape (regular vs paginated inline). Each
class stays at one happy-path test plus one bundled error-paths test, same
pattern as ``test_actions.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import (
    SBAdmin,
    SBAdminTableInline,
    SBAdminTableInlinePaginated,
)
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class FolderPermissionInline(SBAdminTableInline):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0


class FolderPermissionPaginatedInline(SBAdminTableInlinePaginated):
    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0
    per_page = 2  # tiny cap so 3+ children trip truncation


class FolderInlineTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = (
        "id",
        "name",
        SBAdminField(
            name="parent",
            title="Parent",
            annotate=F("parent__name"),
            filter_field="parent",
            filter_widget=AutocompleteFilterWidget(model=Folder, multiselect=False),
        ),
    )
    inlines = [FolderPermissionInline]


class FolderInlinePaginatedTestAdmin(FolderInlineTestAdmin):
    inlines = [FolderPermissionPaginatedInline]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _InlineDataTestBase(TestCase):
    admin_class: type[SBAdmin] = FolderInlineTestAdmin

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, self.admin_class)
        # ``delegate_to_action`` resolves the admin from the configuration
        # singleton's ``view_map`` (built once on first ``__init__``); rebuild
        # it so the in-test ``sb_admin_site.register`` is visible.
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def _list(self, include_inlines, *, user=None):
        user = user or MagicMock(is_authenticated=True, is_superuser=True)
        return SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder", fields=["name"], include_inlines=include_inlines
        )


class IncludeInlinesTests(_InlineDataTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Folder.objects.create(name="alpha")
        cls.beta = Folder.objects.create(name="beta")
        cls.lonely = Folder.objects.create(name="lonely")  # zero perms
        FolderPermission.objects.create(folder=cls.alpha, everybody=True)
        FolderPermission.objects.create(folder=cls.alpha, everybody=False)
        FolderPermission.objects.create(folder=cls.beta, everybody=True)

    def test_grouping_field_subset_and_zero_children(self):
        """One pass over the wire contract: rows grouped by parent pk,
        parents with no children get no ``_inlines`` key, and the spec
        form ``{"inline_name", "fields"}`` projects only the requested
        subset."""
        full = self._list(
            [
                {
                    "inline_name": "FolderPermissionInline",
                    "fields": ["type", "everybody", "can_read"],
                }
            ]
        )
        by_name = {row["name"]: row for row in full["data"]}

        self.assertEqual(len(by_name["alpha"]["_inlines"]["FolderPermissionInline"]), 2)
        self.assertEqual(len(by_name["beta"]["_inlines"]["FolderPermissionInline"]), 1)
        self.assertNotIn("_inlines", by_name["lonely"])

        # Default projection: every declared inline field is present.
        sample_full = by_name["alpha"]["_inlines"]["FolderPermissionInline"][0]
        for col in ("type", "everybody", "can_read"):
            self.assertIn(col, sample_full)

        # Subset projection: only the requested column survives.
        narrow = self._list(
            [{"inline_name": "FolderPermissionInline", "fields": ["everybody"]}]
        )
        sample_narrow = next(
            row["_inlines"]["FolderPermissionInline"][0]
            for row in narrow["data"]
            if row["name"] == "alpha"
        )
        self.assertIn("everybody", sample_narrow)
        self.assertNotIn("can_read", sample_narrow)
        self.assertNotIn("type", sample_narrow)

    def test_error_paths_surface_clear_exceptions(self):
        """Three malformed calls must each raise a distinct, actionable
        exception so the agent can tell the cases apart: unknown inline
        handle, unknown column, denied inline access."""
        with self.assertRaises(LookupError):
            self._list(
                [{"inline_name": "NotARegisteredInline", "fields": ["everybody"]}]
            )

        with self.assertRaises(TypeError):
            self._list(["FolderPermissionInline"])

        with self.assertRaises(TypeError):
            self._list([{"inline_name": "FolderPermissionInline"}])

        with self.assertRaises(LookupError):
            self._list([{"inline_name": "FolderPermissionInline", "fields": ["bogus"]}])

        # Allow the parent admin (so reaching the inline is the failure
        # point), deny the inline target.
        MCPToolTestConfig.view_permission_for = {Folder}
        denied = MagicMock(is_authenticated=True, is_superuser=False)
        with self.assertRaises(PermissionError):
            self._list(
                [{"inline_name": "FolderPermissionInline", "fields": ["everybody"]}],
                user=denied,
            )

    def test_dynamic_get_inlines_can_be_hydrated(self):
        class FolderDynamicInlineAdmin(SBAdmin):
            model = Folder
            sbadmin_list_display = ("id", "name")

            def get_inlines(self, request, obj=None):
                return [FolderPermissionInline]

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderDynamicInlineAdmin)

        result = self._list(
            [{"inline_name": "FolderPermissionInline", "fields": ["everybody"]}]
        )

        alpha = next(row for row in result["data"] if row["name"] == "alpha")
        self.assertEqual(len(alpha["_inlines"]["FolderPermissionInline"]), 2)


class PaginatedInlineCapTests(_InlineDataTestBase):
    """Truncation contract for inlines that opt into ``InlinePaginated``."""

    admin_class = FolderInlinePaginatedTestAdmin

    @classmethod
    def setUpTestData(cls):
        cls.bulky = Folder.objects.create(name="bulky")
        for _ in range(5):  # > per_page (2)
            FolderPermission.objects.create(folder=cls.bulky, everybody=True)
        cls.small = Folder.objects.create(name="small")
        FolderPermission.objects.create(folder=cls.small, everybody=False)

    def test_truncates_to_per_page_and_flags_parent(self):
        """Paginated inline caps rows at ``per_page`` per parent and lists
        over-cap parents in ``_truncated_inlines``; under-cap parents are
        not flagged."""
        result = self._list(
            [
                {
                    "inline_name": "FolderPermissionPaginatedInline",
                    "fields": ["everybody"],
                }
            ]
        )
        by_name = {row["name"]: row for row in result["data"]}

        self.assertEqual(
            len(by_name["bulky"]["_inlines"]["FolderPermissionPaginatedInline"]), 2
        )
        self.assertIn(
            "FolderPermissionPaginatedInline", by_name["bulky"]["_truncated_inlines"]
        )

        self.assertEqual(
            len(by_name["small"]["_inlines"]["FolderPermissionPaginatedInline"]), 1
        )
        self.assertNotIn("_truncated_inlines", by_name["small"])


class FolderPermissionReadonlyInline(SBAdminTableInline):
    """Inline with a callable readonly method — exercises the per-instance
    projection branch of ``get_data_for_parents`` (the cheap ``.values()``
    path doesn't apply when any selected field is a callable)."""

    model = FolderPermission
    fields = ("everybody", "inline_summary")
    readonly_fields = ("inline_summary",)
    extra = 0

    def inline_summary(self, obj):
        return f"inline:{obj.pk}:{obj.everybody}"


class FolderReadonlyInlineTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name")
    inlines = [FolderPermissionReadonlyInline]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class InlineDataBehaviourTests(_InlineDataTestBase):
    """The two non-trivial behaviours of ``get_data_for_parents`` not
    covered by the wire-contract tests above:

    * callable readonly methods on the inline are resolved per-instance
      (any callable selection disables the cheap ``.values()`` path);
    * ``restrict_queryset`` from the role configuration narrows the
      inline queryset, so a parent whose children are filtered out
      gets no ``_inlines`` entry.
    """

    admin_class = FolderReadonlyInlineTestAdmin

    @classmethod
    def setUpTestData(cls):
        cls.parent = Folder.objects.create(name="parent")
        cls.perm_open = FolderPermission.objects.create(
            folder=cls.parent, everybody=True
        )
        cls.perm_closed = FolderPermission.objects.create(
            folder=cls.parent, everybody=False
        )

    def test_callable_readonly_method_is_hydrated(self):
        result = self._list(
            [
                {
                    "inline_name": "FolderPermissionReadonlyInline",
                    "fields": ["everybody", "inline_summary"],
                }
            ]
        )
        parent_row = next(row for row in result["data"] if row["name"] == "parent")
        rows = parent_row["_inlines"]["FolderPermissionReadonlyInline"]
        by_pk = {r["id"]: r for r in rows}
        self.assertEqual(
            by_pk[self.perm_open.pk]["inline_summary"],
            f"inline:{self.perm_open.pk}:True",
        )
        self.assertEqual(
            by_pk[self.perm_closed.pk]["inline_summary"],
            f"inline:{self.perm_closed.pk}:False",
        )

    def test_restrict_queryset_narrows_inline_rows(self):
        """The role configuration's ``restrict_queryset`` hook is the only
        row-level isolation primitive — it must apply to inline queries the
        same way it applies to the parent list."""

        def restrict(qs, model):
            if model is FolderPermission:
                return qs.filter(everybody=True)
            return qs

        MCPToolTestConfig.restrict_qs = staticmethod(restrict)
        try:
            result = self._list(
                [
                    {
                        "inline_name": "FolderPermissionReadonlyInline",
                        "fields": ["everybody"],
                    }
                ]
            )
        finally:
            MCPToolTestConfig.restrict_qs = None

        parent_row = next(row for row in result["data"] if row["name"] == "parent")
        rows = parent_row["_inlines"]["FolderPermissionReadonlyInline"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.perm_open.pk)
