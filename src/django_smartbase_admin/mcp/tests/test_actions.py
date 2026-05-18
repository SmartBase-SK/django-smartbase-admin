"""Tests for ``SBAdminTools.list_rows`` and ``SBAdminTools.autocomplete``.

Drive each tool the same way the live MCP transport would, but via a
``RequestFactory`` request that's been pre-bridged into the SBAdmin
pipeline. Real ``Folder`` rows are created so the tools exercise the
full list-action / autocomplete-search code paths end to end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.const import Action
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)


# Local URLconf so ``reverse("sb_admin:...")`` works inside tests —
# both ``init_view_dynamic`` (action URL resolution) and the list/
# autocomplete pipelines reach for it.
urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class FolderActionsTestAdmin(SBAdmin):
    """Folder admin with one autocomplete filter for end-to-end coverage.

    ``parent`` is annotated to ``parent__name`` so the SBAdminField path
    is exercised; the autocomplete widget targets ``Folder`` itself,
    which is also what we want to query in the autocomplete test.
    """

    model = Folder
    # ``search_fields`` powers the ``full_text_search`` parameter — the
    # list action only applies the term against fields listed here.
    search_fields = ("name",)
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


@override_settings(
    ROOT_URLCONF=__name__,
    # ``list_rows`` / ``autocomplete`` go through ``delegate_to_action``,
    # which calls ``SBAdminConfigurationService.get_configuration`` and
    # rebuilds ``request.request_data`` from scratch. Point the setting
    # at the test config so the singleton ``MCPToolTestConfig`` tests
    # mutate is the same instance ``has_permission_for_action`` ends up
    # using.
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _ToolTestBase(TestCase):
    """Swap a fresh ``FolderActionsTestAdmin`` in per test, restore on
    teardown so we don't clobber other test modules sharing ``Folder``."""

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderActionsTestAdmin)
        self._refresh_configuration_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    @staticmethod
    def _refresh_configuration_view_map():
        """Rebuild ``MCPToolTestConfig.view_map`` from the live registry.

        ``SBAdminRoleConfiguration`` is a singleton: ``init_view_map`` only
        runs on first instantiation. Tests that swap an admin in/out via
        ``sb_admin_site.register`` need this to be visible to
        ``delegate_to_action``, which resolves ``selected_view`` from the
        configuration's cached ``view_map``.
        """
        MCPToolTestConfig().init_view_map()


class ListRowsTests(_ToolTestBase):
    @classmethod
    def setUpTestData(cls):
        # Three rows with predictable, sortable names.
        cls.alpha = Folder.objects.create(name="alpha")
        cls.beta = Folder.objects.create(name="beta")
        cls.gamma = Folder.objects.create(name="gamma")

    def test_browser_shaped_payload_with_pagination_and_search(self):
        """One end-to-end pass over every parameter that affects the
        returned rows: shape (``data``/``last_page``/``last_row``),
        unfiltered rowset, page-size pagination, and ``full_text_search``
        narrowing. Folded into one test so a regression in any single
        knob fails immediately under the same fixture."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))

        # Unpaginated, unfiltered: full payload + every row visible.
        result = tools.list_rows("filer_folder", fields=["name"])
        self.assertIn("data", result)
        self.assertIn("last_page", result)
        self.assertIn("last_row", result)
        self.assertEqual(
            {row["name"] for row in result["data"]}, {"alpha", "beta", "gamma"}
        )
        self.assertEqual(result["last_row"], 3)

        # ``page_size=1`` slices to one row but keeps the unpaginated
        # ``last_row`` total — Tabulator drives pagination off these.
        paged = SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder", fields=["name"], page=1, page_size=1
        )
        self.assertEqual(len(paged["data"]), 1)
        self.assertEqual(paged["last_row"], 3)
        self.assertEqual(paged["last_page"], 3)

        # ``full_text_search`` lives under ``filterData`` in the wire
        # payload — only ``alpha`` should survive.
        searched = SBAdminTools(request=build_mcp_request(user)).list_rows(
            "filer_folder", fields=["name"], full_text_search="alpha"
        )
        self.assertEqual({row["name"] for row in searched["data"]}, {"alpha"})

    def test_error_paths_surface_clear_exceptions(self):
        """Bad ``view_id`` and missing view permission must each raise a
        distinct, actionable exception — agents need to tell "no rows"
        from "no access" or "wrong handle"."""
        user = MagicMock(is_authenticated=True, is_superuser=True)

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).list_rows(
                "does_not_exist", fields=["name"]
            )

        with self.assertRaises(TypeError):
            SBAdminTools(request=build_mcp_request(user)).list_rows(
                "filer_folder", fields=[]
            )

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).list_rows(
                "filer_folder", fields=["no_such_field"]
            )

        denied_user = MagicMock(is_authenticated=True, is_superuser=False)
        MCPToolTestConfig.view_permission_for = set()
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(denied_user)).list_rows(
                "filer_folder", fields=["name"]
            )

    def test_list_rows_respects_action_permission(self):
        class FolderListActionDeniedAdmin(FolderActionsTestAdmin):
            def has_permission_for_action(self, request, action):
                if getattr(action, "action_id", None) == Action.LIST_JSON.value:
                    return False
                return super().has_permission_for_action(request, action)

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderListActionDeniedAdmin)
        self._refresh_configuration_view_map()

        user = MagicMock(is_authenticated=True, is_superuser=True)
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(user)).list_rows(
                "filer_folder", fields=["name"]
            )


class AutocompleteTests(_ToolTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.support = Folder.objects.create(name="support_queue")
        cls.sales = Folder.objects.create(name="sales_queue")
        cls.alpha = Folder.objects.create(name="alpha")

    def test_search_returns_matching_options(self):
        """``autocomplete`` must run the widget's ``search`` against the
        live queryset and return ``{value, label}`` rows the agent can
        feed straight back into ``list_rows`` as a filter value."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_mcp_request(user)

        result = SBAdminTools(request=request).autocomplete(
            "filer_folder", "parent", search="queue"
        )

        # ``Folder.__str__`` renders as a path (``/support_queue``), so
        # match on substring rather than exact equality.
        labels = [row["label"] for row in result]
        self.assertTrue(any("support_queue" in label for label in labels), labels)
        self.assertTrue(any("sales_queue" in label for label in labels), labels)
        self.assertFalse(any("alpha" in label for label in labels), labels)
        # Each row must carry both keys; ``value`` is what callers feed
        # back into ``list_rows(filter_data=...)``.
        for row in result:
            self.assertIn("value", row)
            self.assertIn("label", row)

    def test_error_paths_surface_clear_exceptions(self):
        """Three ways an autocomplete call can be malformed must all
        raise actionable exceptions: unknown field, non-autocomplete
        field, missing view permission."""
        user = MagicMock(is_authenticated=True, is_superuser=True)

        # Typo'd field name.
        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).autocomplete(
                "filer_folder", "no_such_field"
            )

        # Plain column without a filter widget — ``_resolve_filter_widget``
        # raises ``LookupError`` (no widget) or ``TypeError`` (wrong widget
        # class); either is acceptable here.
        with self.assertRaises((LookupError, TypeError)):
            SBAdminTools(request=build_mcp_request(user)).autocomplete(
                "filer_folder", "name"
            )

        # Missing view permission propagates rather than silently
        # returning an empty list.
        denied_user = MagicMock(is_authenticated=True, is_superuser=False)
        MCPToolTestConfig.view_permission_for = set()
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(denied_user)).autocomplete(
                "filer_folder", "parent", search="queue"
            )

    def test_autocomplete_respects_action_permission(self):
        class FolderAutocompleteActionDeniedAdmin(FolderActionsTestAdmin):
            def has_permission_for_action(self, request, action):
                if getattr(action, "action_id", None) == Action.AUTOCOMPLETE.value:
                    return False
                return super().has_permission_for_action(request, action)

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderAutocompleteActionDeniedAdmin)
        self._refresh_configuration_view_map()

        user = MagicMock(is_authenticated=True, is_superuser=True)
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(user)).autocomplete(
                "filer_folder", "parent", search="queue"
            )
