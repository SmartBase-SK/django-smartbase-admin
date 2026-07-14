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
from django.http import JsonResponse
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
        SBAdminField(
            name="editable_name",
            title="Editable name",
            annotate=F("name"),
            tabulator_editor="input",
            filter_disabled=True,
        ),
    )
    sbadmin_fieldsets = ((None, {"fields": ("name", "parent")}),)

    def table_data_edit_form_valid(self, request, form, object_id):
        return JsonResponse(
            {
                "row_id": form.cleaned_data["currentRowId"],
                "column": form.cleaned_data["columnFieldName"],
                "value": form.cleaned_data["cellValue"],
            }
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

    def test_table_data_edit_has_builtin_mcp_form_schema(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        admins = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]
        folder = next(entry for entry in admins if entry["view_id"] == "filer_folder")
        actions = {entry["action_id"]: entry for entry in folder["mcp_actions"]}

        schema = actions[Action.TABLE_DATA_EDIT.value]["components"]["main"]
        self.assertEqual(schema["type"], "form")
        self.assertEqual(
            list(schema["fields"]),
            ["currentRowId", "columnFieldName", "cellValue"],
        )
        self.assertEqual(
            schema["fields"]["columnFieldName"]["choices"],
            [{"value": "editable_name", "label": "Editable name"}],
        )

        result = SBAdminTools(request=build_mcp_request(user)).invoke_action(
            "filer_folder",
            Action.TABLE_DATA_EDIT.value,
            component_values={
                "main": {
                    "currentRowId": 42,
                    "columnFieldName": "editable_name",
                    "cellValue": "updated",
                }
            },
        )
        self.assertEqual(
            result,
            {
                "status": "ok",
                "row_id": 42,
                "column": "editable_name",
                "value": "updated",
            },
        )

        invalid = SBAdminTools(request=build_mcp_request(user)).invoke_action(
            "filer_folder",
            Action.TABLE_DATA_EDIT.value,
            component_values={
                "main": {
                    "currentRowId": 42,
                    "columnFieldName": "name",
                    "cellValue": "updated",
                }
            },
        )
        self.assertEqual(invalid["status"], "invalid")
        main_errors = invalid["errors"]["components"]["main"]
        self.assertEqual(main_errors["type"], "form")
        self.assertIn("columnFieldName", main_errors["fields"])

        invalid_row_id = SBAdminTools(request=build_mcp_request(user)).invoke_action(
            "filer_folder",
            Action.TABLE_DATA_EDIT.value,
            component_values={
                "main": {
                    "currentRowId": "not-json",
                    "columnFieldName": "editable_name",
                    "cellValue": "updated",
                }
            },
        )
        self.assertEqual(invalid_row_id["status"], "invalid")
        row_id_errors = invalid_row_id["errors"]["components"]["main"]
        self.assertIn("currentRowId", row_id_errors["fields"])

        with self.assertRaises(LookupError):
            SBAdminTools(request=build_mcp_request(user)).invoke_action(
                "filer_folder",
                Action.LIST_JSON.value,
            )

    def test_table_data_edit_invalid_form_response_is_overridable(self):
        admin_view = sb_admin_site._registry[Folder]
        form = MagicMock()
        form.is_valid.return_value = False
        admin_view.get_table_data_edit_form = MagicMock(return_value=form)
        admin_view.table_data_edit_form_invalid = MagicMock(
            return_value=JsonResponse({"status": "custom-invalid"}, status=422)
        )

        request = MagicMock(POST={})
        response = admin_view.action_table_data_edit(request, modifier=None)

        self.assertEqual(response.status_code, 422)
        admin_view.table_data_edit_form_invalid.assert_called_once_with(
            request, form, None
        )

    def test_mcp_action_permission_is_checked_before_component_provider(self):
        class FolderTableEditDeniedAdmin(FolderActionsTestAdmin):
            provider_calls = 0

            def get_table_data_edit_form_components(self, request):
                type(self).provider_calls += 1
                return super().get_table_data_edit_form_components(request)

            def has_permission_for_action(self, request, action):
                if action.action_id == Action.TABLE_DATA_EDIT.value:
                    return False
                return super().has_permission_for_action(request, action)

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderTableEditDeniedAdmin)
        self._refresh_configuration_view_map()

        user = MagicMock(is_authenticated=True, is_superuser=True)
        admins = SBAdminTools(request=build_mcp_request(user)).list_admins()[
            "admin_views"
        ]
        folder = next(entry for entry in admins if entry["view_id"] == "filer_folder")
        self.assertNotIn("mcp_actions", folder)
        self.assertEqual(FolderTableEditDeniedAdmin.provider_calls, 0)

        with self.assertRaises(PermissionError):
            SBAdminTools(request=build_mcp_request(user)).invoke_action(
                "filer_folder",
                Action.TABLE_DATA_EDIT.value,
                component_values={
                    "main": {
                        "currentRowId": 42,
                        "columnFieldName": "editable_name",
                        "cellValue": "updated",
                    }
                },
            )
        self.assertEqual(FolderTableEditDeniedAdmin.provider_calls, 0)


class AutocompleteTests(_ToolTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.support = Folder.objects.create(name="support_queue")
        cls.sales = Folder.objects.create(name="sales_queue")
        cls.alpha = Folder.objects.create(name="alpha")

    @staticmethod
    def _filter_widget_id(tools, view_id, field_name):
        """Pull a list-filter ``widget_id`` out of ``list_admins`` — the
        only place an agent legitimately learns it."""
        admins = tools.list_admins()["admin_views"]
        admin_entry = next(a for a in admins if a["view_id"] == view_id)
        field = next(f for f in admin_entry["fields"] if f["name"] == field_name)
        return field["filter"]["widget_id"]

    @staticmethod
    def _detail_widget_id(tools, view_id, object_id, field_name):
        """Pull a detail-form ``widget_id`` out of ``fetch_detail``."""
        detail = tools.fetch_detail(view_id, object_id)
        return detail["components"]["main"]["fields"][field_name]["widget_id"]

    def test_search_returns_matching_options(self):
        """``autocomplete`` must run the widget's ``search`` against the
        live queryset and return ``{value, label}`` rows the agent can
        feed straight back into ``list_rows`` as a filter value."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))
        widget_id = self._filter_widget_id(tools, "filer_folder", "parent")

        result = SBAdminTools(request=build_mcp_request(user)).autocomplete(
            "filer_folder", widget_id, search="queue"
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

    def test_autocomplete_propagates_view_permission_denial(self):
        """Missing view permission propagates rather than silently
        returning an empty list."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        widget_id = self._filter_widget_id(
            SBAdminTools(request=build_mcp_request(user)), "filer_folder", "parent"
        )

        denied_user = MagicMock(is_authenticated=True, is_superuser=False)
        MCPToolTestConfig.view_permission_for = set()
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(denied_user)).autocomplete(
                "filer_folder", widget_id, search="queue"
            )

    def test_form_widget_autocomplete_reuses_dispatch(self):
        """Form-FK autocomplete reuses the same MCP tool: ``fetch_detail``
        surfaces the form widget id, and dispatching with it goes through
        the same ``action_autocomplete`` path as list filters."""

        class FolderFormOnlyAdmin(SBAdmin):
            model = Folder
            sbadmin_list_display = ("id", "name")
            sbadmin_fieldsets = ((None, {"fields": ("name", "parent")}),)

        sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderFormOnlyAdmin)
        self._refresh_configuration_view_map()

        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))
        widget_id = self._detail_widget_id(
            tools, "filer_folder", self.support.pk, "parent"
        )

        result = SBAdminTools(request=build_mcp_request(user)).autocomplete(
            "filer_folder", widget_id, search="queue"
        )

        labels = [row["label"] for row in result]
        self.assertTrue(any("support_queue" in label for label in labels), labels)
        self.assertTrue(any("sales_queue" in label for label in labels), labels)
        self.assertFalse(any("alpha" in label for label in labels), labels)

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
        tools = SBAdminTools(request=build_mcp_request(user))
        widget_id = self._filter_widget_id(tools, "filer_folder", "parent")
        with self.assertRaises(PermissionDenied):
            SBAdminTools(request=build_mcp_request(user)).autocomplete(
                "filer_folder", widget_id, search="queue"
            )
