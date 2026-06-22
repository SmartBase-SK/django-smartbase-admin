"""Tests for ``SBAdminTools.list_admins``.

Drive the toolset method directly with a request that's been pre-bridged
into the SBAdmin pipeline (``request.request_data`` already populated),
mirroring the request-construction pattern used by the nested-plugin
tests. This is the exact same code path the live MCP transport runs
through ``MCPToolset._add_tools_to`` — minus the JSON-RPC framing.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django.db.models import F

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import SBAdminRowAction, sbadmin_action
from django_smartbase_admin.engine.configuration import SBAdminMyProfileConfig
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import (
    AutocompleteFilterWidget,
    MultipleChoiceFilterWidget,
)
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

FOLDER_STATUS_CHOICES = (
    ("draft", "Draft"),
    ("published", "Published"),
)


class FolderListAdminsTestAdmin(SBAdmin):
    """Tiny admin used only for ``list_admins`` schema assertions."""

    model = Folder
    list_display = ("id", "name")


class FolderRichListAdminsTestAdmin(SBAdmin):
    """Richer admin exercising the field/filter schema branch."""

    model = Folder
    sbadmin_list_display = (
        SBAdminField(
            name="status",
            title="Status",
            annotate=F("name"),
            filter_field="status",
            filter_widget=MultipleChoiceFilterWidget(choices=FOLDER_STATUS_CHOICES),
        ),
        SBAdminField(
            name="parent",
            title="Parent",
            annotate=F("parent__name"),
            filter_field="parent",
            filter_widget=AutocompleteFilterWidget(model=Folder, multiselect=False),
        ),
    )


urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(ROOT_URLCONF=__name__)
class ListAdminsTests(TestCase):
    """Each test registers its own ``FolderListAdminsTestAdmin`` and
    restores any pre-existing admin in tearDown so we don't clobber
    other test modules that also register against ``Folder``."""

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderListAdminsTestAdmin)
        # Reset per-test permission scope on the shared singleton config.
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig().myprofile_sbadmin = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig().myprofile_sbadmin = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def test_returns_full_admin_schema_sorted_by_view_id(self):
        """Happy path: every visible admin surfaces with the documented
        schema, default ``search_fields`` is empty (no full-text search
        configured), and entries are sorted by ``view_id``."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_mcp_request(user)

        result = SBAdminTools(request=request).list_admins()["admin_views"]

        view_ids = [e["view_id"] for e in result]
        self.assertEqual(view_ids, sorted(view_ids))

        folder_entries = [e for e in result if e["view_id"] == "filer_folder"]
        self.assertEqual(len(folder_entries), 1, result)
        entry = folder_entries[0]
        self.assertEqual(entry["app_label"], "filer")
        self.assertEqual(entry["model"], "Folder")
        # Implementation-detail keys we deliberately removed from the
        # public schema: ``admin_name``, ``base_model``, ``is_proxy``.
        self.assertNotIn("admin_name", entry)
        self.assertNotIn("base_model", entry)
        self.assertNotIn("is_proxy", entry)
        # Plain string list_display entries surface as ``{"name": ...}``
        # only — there's no SBAdminField to resolve titles or filters from.
        self.assertEqual([f["name"] for f in entry["fields"]], ["id", "name"])
        self.assertTrue(entry["verbose_name"])
        self.assertTrue(entry["verbose_name_plural"])
        # Default admin has no ``search_fields`` → empty list signals
        # that ``full_text_search`` is a no-op for this admin.
        self.assertEqual(entry["search_fields"], [])

    def test_my_profile_is_omitted_when_unconfigured(self):
        user = MagicMock(
            id=1, is_authenticated=True, is_anonymous=False, is_superuser=True
        )

        result = SBAdminTools(request=build_mcp_request(user)).list_admins()

        self.assertNotIn("my_profile", result)

    def test_my_profile_surfaces_configured_current_user_detail_target(self):
        folder = Folder.objects.create(name="profile")
        user = MagicMock(
            pk=folder.pk,
            id=folder.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=True,
        )
        MCPToolTestConfig().myprofile_sbadmin = SBAdminMyProfileConfig(
            view_id="filer_folder"
        )

        result = SBAdminTools(request=build_mcp_request(user)).list_admins()

        self.assertEqual(
            result["my_profile"],
            {"view_id": "filer_folder", "object_id": str(folder.pk)},
        )

    def test_my_profile_surfaces_configured_target_without_eager_object_check(self):
        folder = Folder.objects.create(name="profile")
        user = MagicMock(
            pk=folder.pk,
            id=folder.pk,
            is_authenticated=True,
            is_anonymous=False,
            is_superuser=False,
        )
        MCPToolTestConfig().myprofile_sbadmin = SBAdminMyProfileConfig(
            view_id="filer_folder"
        )
        MCPToolTestConfig.view_permission_for = set()

        result = SBAdminTools(request=build_mcp_request(user)).list_admins()

        self.assertEqual(
            result["my_profile"],
            {"view_id": "filer_folder", "object_id": str(folder.pk)},
        )

    def test_my_profile_is_omitted_for_anonymous_user(self):
        folder = Folder.objects.create(name="profile")
        user = MagicMock(
            pk=folder.pk,
            id=folder.pk,
            is_active=True,
            is_staff=True,
            is_authenticated=False,
            is_anonymous=True,
            is_superuser=True,
        )
        MCPToolTestConfig().myprofile_sbadmin = SBAdminMyProfileConfig(
            view_id="filer_folder"
        )

        result = SBAdminTools(request=build_mcp_request(user)).list_admins()

        self.assertNotIn("my_profile", result)

    def test_permission_filtering_includes_or_excludes_admin(self):
        """Two halves of the same contract — empty scope hides the admin,
        explicit scope reveals it. Folded together so a regression in
        either direction surfaces immediately."""
        user = MagicMock(is_authenticated=True, is_superuser=False)

        MCPToolTestConfig.view_permission_for = set()
        view_ids = [
            e["view_id"]
            for e in SBAdminTools(request=build_mcp_request(user)).list_admins()[
                "admin_views"
            ]
        ]
        self.assertNotIn("filer_folder", view_ids)

        MCPToolTestConfig.view_permission_for = {Folder}
        view_ids = [
            e["view_id"]
            for e in SBAdminTools(request=build_mcp_request(user)).list_admins()[
                "admin_views"
            ]
        ]
        self.assertIn("filer_folder", view_ids)

    def test_proxy_model_surfaces_with_own_view_id(self):
        """Proxy admins surface as their own entry, distinguishable by
        ``view_id`` and ``model`` from the concrete admin."""

        class FolderProxy(Folder):
            class Meta:
                proxy = True
                app_label = "filer"

        class FolderProxyAdmin(SBAdmin):
            model = FolderProxy
            list_display = ("name",)

        sb_admin_site._registry.pop(FolderProxy, None)
        sb_admin_site.register(FolderProxy, FolderProxyAdmin)
        try:
            user = MagicMock(is_authenticated=True, is_superuser=True)
            request = build_mcp_request(user)

            result = SBAdminTools(request=request).list_admins()["admin_views"]

            view_ids = {e["view_id"]: e for e in result}
            self.assertIn("filer_folder", view_ids)
            self.assertIn("filer_folderproxy", view_ids)
            self.assertEqual(view_ids["filer_folderproxy"]["model"], "FolderProxy")
        finally:
            sb_admin_site._registry.pop(FolderProxy, None)

    def test_bridge_is_a_no_op_when_request_data_already_set(self):
        """``_ensure_sbadmin_request_data`` must respect a pre-bridged
        request — otherwise tests with mocked configurations would have
        their fixture clobbered by ``SBAdminConfigurationService``."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_mcp_request(user)
        original_config = request.request_data.configuration

        SBAdminTools(request=request).list_admins()["admin_views"]

        self.assertIs(request.request_data.configuration, original_config)

    def test_search_fields_surface_when_admin_declares_them(self):
        """``search_fields`` must mirror what the admin would actually
        match against in ``list_rows(full_text_search=...)``. The empty
        / no-op case is covered by ``test_returns_full_admin_schema...``;
        this test exercises the populated branch."""

        class FolderSearchableAdmin(SBAdmin):
            model = Folder
            list_display = ("id", "name")
            search_fields = ("name",)

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderSearchableAdmin)

        user = MagicMock(is_authenticated=True, is_superuser=True)
        result = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]

        entry = next(e for e in result if e["view_id"] == "filer_folder")
        self.assertEqual(entry["search_fields"], ["name"])

    def test_nested_row_actions_surface_in_schema(self):
        class FolderNestedRowActionsAdmin(SBAdmin):
            model = Folder
            list_display = ("id", "name")

            @sbadmin_action
            def action_archive_folder(self, request, modifier, object_id):
                from django.http import HttpResponse

                return HttpResponse("")

            def get_sbadmin_row_actions(self, request):
                return [
                    SBAdminRowAction(
                        title="More",
                        icon="More",
                        sub_actions=[
                            SBAdminRowAction(
                                action_id="action_archive_folder",
                                title="Archive",
                                icon="Delete",
                                view=self,
                            ),
                            SBAdminRowAction(
                                url="/folders/__object_id__/",
                                title="Open",
                                icon="Preview-open",
                            ),
                        ],
                    )
                ]

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderNestedRowActionsAdmin)
        MCPToolTestConfig().init_view_map()

        user = MagicMock(is_authenticated=True, is_superuser=True)
        result = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]

        entry = next(e for e in result if e["view_id"] == "filer_folder")
        # MCP discovery flattens visual sub-action dropdowns to invocable
        # leaves and drops url-only entries (agents can't invoke them).
        # ``invoke_with`` no longer lives per-entry; the MCP tool to call
        # for each action list is published once at the top level via
        # ``action_invokers`` (``row_actions`` → ``invoke_row_action``).
        self.assertEqual(
            entry["row_actions"],
            [
                {
                    "title": "Archive",
                    "kind": "method",
                    "action_id": "action_archive_folder",
                },
            ],
        )

    def test_field_filter_schema(self):
        """Resolved field entries surface filter widget metadata.

        Re-registers the Folder admin with a richer ``sbadmin_list_display``
        so we can assert: choice widgets carry ``choices``; autocomplete
        widgets carry ``multiselect``/``target_model``; the filter info
        comes from a *deep copy* of the field, not the shared singleton.
        """
        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderRichListAdminsTestAdmin)

        # Snapshot the registered field's filter widget so we can prove
        # the call didn't mutate it.
        registered_admin = sb_admin_site._registry[Folder]
        original_widgets = [
            f.filter_widget for f in registered_admin.sbadmin_list_display
        ]

        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_mcp_request(user)
        result = SBAdminTools(request=request).list_admins()["admin_views"]

        entry = next(e for e in result if e["view_id"] == "filer_folder")
        fields_by_name = {f["name"]: f for f in entry["fields"]}

        status = fields_by_name["status"]
        self.assertEqual(status["title"], "Status")
        self.assertEqual(status["filter"]["widget"], "MultipleChoiceFilterWidget")
        # The filter is keyed by the column ``name`` in list_rows; the
        # internal ``filter_field`` is not surfaced.
        self.assertNotIn("filter_field", status["filter"])
        self.assertEqual(
            status["filter"]["choices"],
            [
                {"value": "draft", "label": "Draft"},
                {"value": "published", "label": "Published"},
            ],
        )

        parent = fields_by_name["parent"]
        self.assertEqual(parent["filter"]["widget"], "AutocompleteFilterWidget")
        self.assertFalse(parent["filter"]["multiselect"])
        self.assertEqual(parent["filter"]["target_model"], "filer.Folder")

        # Live admin's shared filter widgets must be untouched (init was
        # run on a deep copy, not the registered field).
        for original, field in zip(
            original_widgets, registered_admin.sbadmin_list_display
        ):
            self.assertIs(field.filter_widget, original)

    def test_dynamic_get_inlines_surface_in_schema(self):
        class DynamicPermissionInline(SBAdminTableInline):
            model = FolderPermission
            fields = ("type",)

        class FolderDynamicInlineAdmin(SBAdmin):
            model = Folder
            list_display = ("id", "name")

            def get_inlines(self, request, obj=None):
                return [DynamicPermissionInline]

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderDynamicInlineAdmin)

        user = MagicMock(is_authenticated=True, is_superuser=True)
        result = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]

        entry = next(e for e in result if e["view_id"] == "filer_folder")
        self.assertIn(
            "DynamicPermissionInline",
            {inline["inline_name"] for inline in entry["inlines"]},
        )
