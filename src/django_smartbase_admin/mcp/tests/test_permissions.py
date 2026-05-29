"""End-to-end permission propagation across the MCP surface.

One test per gap not already covered by ``test_actions.py``,
``test_inline_data.py``, or ``test_fake_inlines.py``:

* ``list_admins`` schema filters out inlines whose
  ``has_view_or_change_permission`` is False — covered for the data
  path elsewhere; here for the schema path.
* ``restrict_queryset`` (row-level isolation hook on
  ``SBAdminRoleConfiguration``) narrows ``list_rows`` rows AND
  ``autocomplete`` options.
* Per-user dynamic ``get_sbadmin_list_display(request)`` shapes the
  schema and gates ``list_rows(fields=...)`` / ``autocomplete(field_name=
  ...)`` — the de-facto field-level permission gate in SBAdmin.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder, FolderPermission

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class PermissionFolderPermissionInline(SBAdminTableInline):
    """Inline whose ``get_fields(request, obj)`` narrows the allowed field
    set for non-superusers — the dynamic field-allowlist hook MCP's
    ``_resolve_inline_data_fields`` reads on every call.
    """

    model = FolderPermission
    fields = ("type", "everybody", "can_read")
    extra = 0

    def get_fields(self, request, obj=None):
        if request.user.is_superuser:
            return self.fields
        return ("everybody",)


_PARENT_FIELD = SBAdminField(
    name="parent",
    title="Parent",
    annotate=F("parent__name"),
    filter_field="parent",
    filter_widget=AutocompleteFilterWidget(model=Folder, multiselect=False),
)


class PerUserFolderAdmin(SBAdmin):
    """Hides the ``parent`` autocomplete column from non-superusers.

    SBAdmin has no first-class field-permission API; the per-request
    ``get_sbadmin_list_display`` is the actual gate. The MCP layer is
    expected to trust it all the way through schema, list_rows, and
    autocomplete.
    """

    model = Folder
    search_fields = ("name",)
    inlines = [PermissionFolderPermissionInline]
    sbadmin_list_display = ("id", "name", _PARENT_FIELD)

    def get_sbadmin_list_display(self, request):
        if request.user.is_superuser:
            return self.sbadmin_list_display
        return self.sbadmin_list_display[:2]  # drop "parent"


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class TestMCPPermissions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Folder.objects.create(name="alpha_perm")
        cls.beta = Folder.objects.create(name="beta_perm")
        cls.hidden = Folder.objects.create(name="hidden_perm")

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, PerUserFolderAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig.restrict_qs = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        MCPToolTestConfig.restrict_qs = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def test_non_staff_user_is_denied_despite_model_permission(self):
        """MCP tools never pass through ``admin_view()``, so the staff gate
        must be enforced in-band. A user with model view permission but
        ``is_staff=False`` is rejected; flipping ``is_staff`` on lets the
        same call through — proving staff status, not model perms, is the
        gate."""
        MCPToolTestConfig.view_permission_for = {Folder}
        non_staff = MagicMock(
            is_authenticated=True, is_active=True, is_staff=False, is_superuser=False
        )
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(non_staff)).list_admins()

        staff = MagicMock(
            is_authenticated=True, is_active=True, is_staff=True, is_superuser=False
        )
        admins = SBAdminTools(request=build_mcp_request(staff)).list_admins()[
            "admin_views"
        ]
        self.assertTrue(any(a["view_id"] == "filer_folder" for a in admins))

    def test_schema_omits_inline_user_cannot_view(self):
        """``list_admins.inlines`` skips inlines failing
        ``has_view_or_change_permission`` — parent admin stays visible so
        the agent learns the surface exists, the denied inline disappears."""
        MCPToolTestConfig.view_permission_for = {Folder}
        denied = MagicMock(is_authenticated=True, is_superuser=False)
        admins = SBAdminTools(request=build_mcp_request(denied)).list_admins()[
            "admin_views"
        ]
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        inline_names = {entry["inline_name"] for entry in folder["inlines"]}
        self.assertNotIn("PermissionFolderPermissionInline", inline_names)

    def test_restrict_queryset_narrows_list_rows_and_autocomplete(self):
        """``restrict_queryset`` is the row-level isolation hook on
        ``SBAdminRoleConfiguration``. Both ``list_rows`` (parent qs) and
        ``autocomplete`` (filter widget target qs) must honor it — anything
        less leaks rows to an MCP caller that the browser would never see.
        """
        MCPToolTestConfig.restrict_qs = lambda qs, model: (
            qs.exclude(name__startswith="hidden") if model is Folder else qs
        )
        user = MagicMock(is_authenticated=True, is_superuser=True)

        tools = SBAdminTools(request=build_mcp_request(user))
        admins = tools.list_admins()["admin_views"]
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        parent_widget_id = next(
            f["filter"]["widget_id"] for f in folder["fields"] if f["name"] == "parent"
        )

        rows = SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder", fields=["name"], full_text_search="perm"
        )
        names = {row["name"] for row in rows["data"]}
        self.assertIn("alpha_perm", names)
        self.assertNotIn("hidden_perm", names)

        auto = SBAdminTools(request=build_mcp_request(user)).autocomplete(
            "filer_folder", parent_widget_id, search="perm"
        )
        labels = " ".join(row["label"] for row in auto)
        self.assertIn("alpha_perm", labels)
        self.assertNotIn("hidden_perm", labels)

    def test_dynamic_list_display_gates_schema_and_field_handles(self):
        """``get_sbadmin_list_display(request)`` is the de-facto
        field-level permission gate. The same hidden field must:

        * not appear in ``list_admins.fields`` for the restricted user,
        * raise ``LookupError`` from ``list_rows(fields=[hidden])``,
        * raise ``LookupError`` from ``autocomplete(field_name=hidden)``.

        Folded into one test because the three branches all derive from
        the same per-request field-map source — a regression in any one
        means the dynamic display hook is being bypassed.
        """
        allowed = MagicMock(is_authenticated=True, is_superuser=True)
        denied = MagicMock(is_authenticated=True, is_superuser=False)

        super_admins = SBAdminTools(request=build_mcp_request(allowed)).list_admins()[
            "admin_views"
        ]
        super_folder = next(a for a in super_admins if a["view_id"] == "filer_folder")
        self.assertIn("parent", {f["name"] for f in super_folder["fields"]})

        admins = SBAdminTools(request=build_mcp_request(denied)).list_admins()[
            "admin_views"
        ]
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        names = {f["name"] for f in folder["fields"]}
        self.assertNotIn("parent", names)
        self.assertIn("name", names)

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(denied)).list_rows(
                "filer_folder", fields=["parent"]
            )

        parent_widget_id = next(
            f["filter"]["widget_id"]
            for f in super_folder["fields"]
            if f["name"] == "parent"
        )
        # A widget the user can't see is "not found" for them — same
        # ``LookupError`` as the ``fields=[hidden]`` branch, no existence leak.
        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(denied)).autocomplete(
                "filer_folder", parent_widget_id, search="perm"
            )

    def test_inline_fields_respect_dynamic_get_fields(self):
        """Inline ``get_fields(request, obj)`` is the dynamic field-allowlist
        for inlines. MCP must surface the per-user subset in
        ``list_admins.inlines[].fields`` AND reject ``include_inlines=
        [{fields: [hidden]}]`` calls — same shape as the parent-admin
        gate, just one layer deeper.
        """
        denied = MagicMock(is_authenticated=True, is_superuser=False)

        admins = SBAdminTools(request=build_mcp_request(denied)).list_admins()[
            "admin_views"
        ]
        folder = next(a for a in admins if a["view_id"] == "filer_folder")
        inline = next(
            entry
            for entry in folder["inlines"]
            if entry["inline_name"] == "PermissionFolderPermissionInline"
        )
        self.assertEqual(inline["fields"], ["everybody"])

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(denied)).list_rows(
                "filer_folder",
                fields=["name"],
                include_inlines=[
                    {
                        "inline_name": "PermissionFolderPermissionInline",
                        "fields": ["can_read"],
                    }
                ],
            )
