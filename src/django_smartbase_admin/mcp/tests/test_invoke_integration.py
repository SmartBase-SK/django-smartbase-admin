"""Integration tests for invoke / delete tools.

Each test drives a full round-trip through ``SBAdminTools`` against
``FolderInvokeTestAdmin``: discovery → dispatch → DB write → response
shape. Tests are deliberately end-to-end so a regression anywhere on
the dispatch path (lookup, registration, encoding, normalizer) breaks
something visible.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

from django import forms
from django.contrib import messages
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import File, Folder

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminFormViewAction,
    SBAdminRowAction,
    sbadmin_action,
)
from django_smartbase_admin.engine.modal_view import (
    ActionModalView,
    ListActionModalView,
    RowActionModalView,
    SBAdminActionError,
)
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class _RenameForm(forms.Form):
    name = forms.CharField()


class RenameFolderModalView(RowActionModalView):
    form_class = _RenameForm
    modal_title = "Rename Folder"

    def process_form_valid(self, request, form):
        obj = self.get_object()
        obj.name = form.cleaned_data["name"]
        obj.save()
        messages.success(request, f"Renamed to {obj.name}.")
        return super().process_form_valid(request, form)


class _BulkRenameForm(forms.Form):
    suffix = forms.CharField()


class BulkRenameModalView(ListActionModalView):
    form_class = _BulkRenameForm
    modal_title = "Append suffix"
    success_message = "Renamed {count} folder{plural}."

    def process_form_valid_list_selection_queryset(self, request, form, queryset):
        suffix = form.cleaned_data["suffix"]
        count = 0
        for obj in queryset:
            obj.name = f"{obj.name}{suffix}"
            obj.save()
            count += 1
        return count


class _CreateForm(forms.Form):
    name = forms.CharField()


class CreateFolderModalView(ActionModalView):
    form_class = _CreateForm
    modal_title = "Create Folder"
    requires_confirmation = True
    confirmation_message = "Create a folder called {name!r}?"

    def get_confirmation_data(self, request, form):
        return {"name": form.cleaned_data["name"]}

    def process_form_valid(self, request, form):
        obj = Folder.objects.create(name=form.cleaned_data["name"])
        messages.success(request, f"Created {obj.name}.")
        return super().process_form_valid(request, form)


class _InlineNoteForm(forms.Form):
    note = forms.CharField()


class InlineRowRenameModalView(RowActionModalView):
    """Inline row modal — exercises ``self.view.get_queryset`` against
    the inline (not the parent), so a wrongly-resolved view_id / pk
    pair fails loudly."""

    form_class = _InlineNoteForm
    modal_title = "Rename file"
    requires_confirmation = True
    confirmation_message = "Rename to {new_name!r}?"

    def get_confirmation_data(self, request, form):
        obj = self.get_object()
        if obj is None:
            raise SBAdminActionError("Inline row not found.")
        return {"new_name": form.cleaned_data["note"], "current": obj.name}

    def process_form_valid(self, request, form):
        obj = self.get_object()
        obj.name = form.cleaned_data["note"]
        obj.save()
        messages.success(request, f"Renamed file to {obj.name}.")
        return super().process_form_valid(request, form)


class FolderFileInline(SBAdminTableInline):
    model = File
    fk_name = "folder"
    fields = ("name",)
    extra = 0
    can_delete = False
    max_num = 0

    def get_sbadmin_inline_list_actions(self, request):
        return [
            SBAdminCustomAction(title="Help", url="/help/"),
            SBAdminFormViewAction(
                target_view=InlineRowRenameModalView,
                title="Rename file",
                view=self,
            ),
        ]


class FolderInvokeTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name")
    sbadmin_fieldsets = ((None, {"fields": ("name",)}),)
    inlines = [FolderFileInline]

    @sbadmin_action
    def action_touch(self, request, modifier, object_id):
        obj = self.get_queryset(request).get(pk=object_id)
        obj.name = f"{obj.name}!"
        obj.save()
        messages.success(request, f"Touched {obj.name}.")
        from django.http import HttpResponse

        return HttpResponse("")

    @sbadmin_action
    def action_archive(self, request, modifier, object_id):
        obj = self.get_queryset(request).get(pk=object_id)
        messages.success(request, f"Archived {obj.name}.")
        from django.http import HttpResponse

        return HttpResponse("")

    @sbadmin_action
    def action_export_bytes(self, request, modifier, object_id):
        """Returns a small binary blob with Content-Disposition so the
        MCP normalizer embeds it as a resource for download."""
        from django.http import HttpResponse

        body = b"PK\x03\x04fake-xlsx-bytes"
        response = HttpResponse(body, content_type="application/vnd.ms-excel")
        response["Content-Disposition"] = 'attachment; filename="export.xlsx"'
        return response

    def get_sbadmin_row_actions(self, request):
        return [
            SBAdminRowAction(
                title="Rename",
                icon="Edit",
                target_view=RenameFolderModalView,
                view=self,
            ),
            SBAdminRowAction(
                title="Touch",
                icon="Plus",
                action_id="action_touch",
                view=self,
            ),
            SBAdminRowAction(
                title="Export",
                icon="Download",
                action_id="action_export_bytes",
                view=self,
            ),
        ]

    def get_sbadmin_detail_actions(self, request, object_id=None):
        return [
            SBAdminCustomAction(
                title="Archive",
                view=self,
                action_id="action_archive",
            ),
        ]

    def get_sbadmin_list_selection_actions(self, request):
        return [
            SBAdminFormViewAction(
                target_view=BulkRenameModalView,
                title="Append Suffix",
                view=self,
            ),
        ]

    def get_sbadmin_list_actions(self, request):
        return [
            SBAdminFormViewAction(
                target_view=CreateFolderModalView,
                title="Create Folder",
                view=self,
            ),
            SBAdminCustomAction(title="External", url="/external/"),
        ]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class _Base(TestCase):
    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderInvokeTestAdmin)
        config = MCPToolTestConfig()
        config.init_view_map()
        # Populate ``view_map`` with inline instances too — they are
        # registered under their own ``get_id()`` for inline-action
        # invocation and would otherwise raise 404 on dispatch.
        config.init_model_admin_view_map()
        MCPToolTestConfig.view_permission_for = None
        self.user = MagicMock(is_authenticated=True, is_superuser=True)

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def _tools(self):
        return SBAdminTools(request=build_mcp_request(self.user))


class IntegrationTests(_Base):
    def test_discovery_classifies_actions_and_filters_unsupported(self):
        """``list_admins`` separates actions by source with correct kinds and
        ``requires_confirmation`` flags; URL-only and bulk_delete are hidden."""
        admins = self._tools().list_admins()["admin_views"]
        folder = next(a for a in admins if a["view_id"] == "filer_folder")

        row = {a["title"]: a for a in folder["row_actions"]}
        self.assertEqual(row["Rename"]["kind"], "modal")
        self.assertEqual(row["Rename"]["action_id"], "RenameFolderModalView")
        self.assertEqual(row["Touch"]["kind"], "method")

        detail = {a["title"]: a for a in folder["detail_actions"]}
        self.assertEqual(detail["Archive"]["action_id"], "action_archive")

        list_titles = {a["title"]: a for a in folder["list_actions"]}
        self.assertNotIn("External", list_titles)  # URL-only filtered
        self.assertTrue(list_titles["Create Folder"]["requires_confirmation"])

        sel_titles = {a["title"] for a in folder["selection_actions"]}
        self.assertNotIn("Delete Selected", sel_titles)  # bulk_delete filtered

        inlines = {i["inline_name"]: i for i in folder["inlines"]}
        inline_entry = inlines["FolderFileInline"]
        # Inlines have their own view_id — dispatched through their own URL
        # namespace, not the parent's. Agents pass this view_id to
        # invoke_inline_action for inline modal actions.
        self.assertTrue(inline_entry["view_id"])
        self.assertNotEqual(inline_entry["view_id"], folder["view_id"])
        inline_titles = {a["title"]: a for a in inline_entry["inline_actions"]}
        self.assertNotIn("Help", inline_titles)  # URL-only filtered inside inlines too
        self.assertTrue(inline_titles["Rename file"]["requires_confirmation"])

    def test_row_modal_round_trip_persists_and_handles_invalid(self):
        """fetch_action_form → invoke → DB write → messages; invalid submission
        keeps the row untouched and surfaces per-field errors (no ``__all__``)."""
        folder = Folder.objects.create(name="original")

        schema = self._tools().fetch_action_form(
            "filer_folder", "RenameFolderModalView", object_id=str(folder.pk)
        )
        self.assertTrue(schema["fields"]["name"]["required"])

        bad = self._tools().invoke_row_action(
            "filer_folder",
            "RenameFolderModalView",
            object_id=str(folder.pk),
            field_values={"name": ""},
        )
        self.assertEqual(bad["status"], "invalid")
        self.assertIn("name", bad["errors"])
        self.assertNotIn("__all__", bad["errors"])
        folder.refresh_from_db()
        self.assertEqual(folder.name, "original")

        ok = self._tools().invoke_row_action(
            "filer_folder",
            "RenameFolderModalView",
            object_id=str(folder.pk),
            field_values={"name": "renamed"},
        )
        self.assertEqual(ok["status"], "ok")
        folder.refresh_from_db()
        self.assertEqual(folder.name, "renamed")
        self.assertTrue(any("Renamed" in m["message"] for m in ok["messages"]))

    def test_row_method_action_dispatches_and_rejects_field_values(self):
        """Method-kind actions take no ``field_values`` and that's enforced."""
        folder = Folder.objects.create(name="m")
        ok = self._tools().invoke_row_action(
            "filer_folder", "action_touch", object_id=str(folder.pk)
        )
        self.assertEqual(ok["status"], "ok")
        folder.refresh_from_db()
        self.assertEqual(folder.name, "m!")

        with self.assertRaises(LookupError):
            self._tools().invoke_row_action(
                "filer_folder",
                "action_touch",
                object_id=str(folder.pk),
                field_values={"x": "y"},
            )

    def test_selection_modal_persists_and_surfaces_count_message(self):
        """Hook-returned count templates through ``success_message`` and
        reaches the agent via the message channel."""
        a = Folder.objects.create(name="a")
        b = Folder.objects.create(name="b")
        result = self._tools().invoke_selection_action(
            "filer_folder",
            "BulkRenameModalView",
            object_ids=[str(a.pk), str(b.pk)],
            field_values={"suffix": "_x"},
        )
        self.assertEqual(result["status"], "ok")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.name, "a_x")
        self.assertEqual(b.name, "b_x")
        self.assertTrue(
            any("Renamed 2 folders." in m["message"] for m in result["messages"])
        )

    def test_confirmation_framework_two_step_create(self):
        """First call returns ``needs_confirmation`` with structured data +
        formatted message and DOES NOT commit; ``confirmed=True`` commits."""
        first = self._tools().invoke_list_action(
            "filer_folder", "CreateFolderModalView", field_values={"name": "x"}
        )
        self.assertEqual(first["status"], "needs_confirmation")
        self.assertEqual(first["data"], {"name": "x"})
        self.assertEqual(first["message"], "Create a folder called 'x'?")
        self.assertFalse(Folder.objects.filter(name="x").exists())

        second = self._tools().invoke_list_action(
            "filer_folder",
            "CreateFolderModalView",
            field_values={"name": "x"},
            confirmed=True,
        )
        self.assertEqual(second["status"], "ok")
        self.assertTrue(Folder.objects.filter(name="x").exists())

    def test_detail_action_routes_through_alias(self):
        """``invoke_detail_action`` is a thin alias over the row dispatch."""
        folder = Folder.objects.create(name="d")
        result = self._tools().invoke_detail_action(
            "filer_folder", "action_archive", object_id=str(folder.pk)
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(any("Archived d" in m["message"] for m in result["messages"]))

    def test_inline_modal_acts_on_inline_row_via_inline_view_id(self):
        """Inline modal action operates on an INLINE row identified by the
        inline's own ``view_id`` and an inline row pk. The modal calls
        ``self.get_object()`` against the inline's queryset — a wrongly-
        resolved view_id / pk would either return no object or the wrong
        one, breaking the test loudly."""
        folder = Folder.objects.create(name="parent")
        file_row = File.objects.create(folder=folder, name="orig.txt")

        # Discovery: pick up the inline's view_id from the parent's entry.
        folder_entry = next(
            a
            for a in self._tools().list_admins()["admin_views"]
            if a["view_id"] == "filer_folder"
        )
        inline = next(
            i for i in folder_entry["inlines"] if i["inline_name"] == "FolderFileInline"
        )
        inline_view_id = inline["view_id"]

        # fetch_action_form on the inline's view_id with the inline row's pk.
        schema = self._tools().fetch_action_form(
            inline_view_id,
            "InlineRowRenameModalView",
            object_id=str(file_row.pk),
        )
        self.assertIn("note", schema["fields"])

        first = self._tools().invoke_inline_action(
            inline_view_id,
            "InlineRowRenameModalView",
            object_id=str(file_row.pk),
            field_values={"note": "renamed.txt"},
        )
        self.assertEqual(first["status"], "needs_confirmation")
        # ``current`` only resolves if ``get_object()`` walked the inline's
        # queryset with the right pk.
        self.assertEqual(first["data"]["new_name"], "renamed.txt")
        self.assertEqual(first["data"]["current"], "orig.txt")

        second = self._tools().invoke_inline_action(
            inline_view_id,
            "InlineRowRenameModalView",
            object_id=str(file_row.pk),
            field_values={"note": "renamed.txt"},
            confirmed=True,
        )
        self.assertEqual(second["status"], "ok")
        file_row.refresh_from_db()
        self.assertEqual(file_row.name, "renamed.txt")

    def test_audit_history_scoped_to_object_and_gated_by_flag(self):
        """``get_audit_history`` returns log entries for the admin's model
        (optionally narrowed to one object). Disabled when
        ``sbadmin_list_history_enabled = False`` on the admin."""
        from django.contrib.contenttypes.models import ContentType

        from django_smartbase_admin.audit.models import AdminAuditLog

        folder = Folder.objects.create(name="hist")
        # Second real folder so the second audit row survives the audit
        # admin's ``restrict_queryset`` gate (a non-existent object_id
        # would be filtered out).
        other_folder = Folder.objects.create(name="other")
        # Drop the audit framework's automatic create entries so the
        # assertions count only the explicit rows we're about to set up.
        AdminAuditLog.objects.all().delete()
        AdminAuditLog.objects.create(
            content_type=ContentType.objects.get_for_model(Folder),
            object_id=str(folder.pk),
            object_repr="hist",
            action_type="create",
        )
        # Entry against a different folder; must not appear when scoped to
        # the first folder.
        AdminAuditLog.objects.create(
            content_type=ContentType.objects.get_for_model(Folder),
            object_id=str(other_folder.pk),
            object_repr="other",
            action_type="delete",
        )

        scoped = self._tools().get_audit_history(
            "filer_folder",
            object_id=str(folder.pk),
        )
        self.assertEqual(scoped["last_row"], 1)
        self.assertEqual(scoped["data"][0]["object_id"], str(folder.pk))
        self.assertEqual(scoped["data"][0]["action_type"], "create")

        all_rows = self._tools().get_audit_history("filer_folder")
        self.assertEqual(all_rows["last_row"], 2)

        # Disable history on the admin → tool raises LookupError.
        FolderInvokeTestAdmin.sbadmin_list_history_enabled = False
        try:
            with self.assertRaises(LookupError):
                self._tools().get_audit_history("filer_folder")
        finally:
            FolderInvokeTestAdmin.sbadmin_list_history_enabled = True

    def test_method_action_returning_binary_embeds_resource(self):
        """A method action that returns binary content surfaces as an MCP
        embedded resource — text status block + ``BlobResourceContents``
        with base64 payload and the parsed filename from
        ``Content-Disposition``."""
        from mcp.types import EmbeddedResource

        folder = Folder.objects.create(name="bin")
        result = self._tools().invoke_row_action(
            "filer_folder",
            "action_export_bytes",
            object_id=str(folder.pk),
        )

        # Result is a list of content blocks (status JSON text + resource).
        self.assertIsInstance(result, list)
        status = json.loads(result[0])
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["file"]["filename"], "export.xlsx")
        self.assertEqual(status["file"]["content_type"], "application/vnd.ms-excel")

        # Embedded resource carries the base64-encoded blob.
        resource = next(b for b in result if isinstance(b, EmbeddedResource))
        decoded = base64.b64decode(resource.resource.blob)
        self.assertEqual(decoded, b"PK\x03\x04fake-xlsx-bytes")
        self.assertEqual(resource.resource.mimeType, "application/vnd.ms-excel")

    def test_delete_objects_preview_then_commit(self):
        """Preview returns count/sample/cascade without deleting; ``confirmed``
        deletes only the targeted row and surfaces the count via messages."""
        target = Folder.objects.create(name="to-delete")
        bystander = Folder.objects.create(name="keep")

        preview = self._tools().delete_objects(
            "filer_folder", object_ids=[str(target.pk)]
        )
        self.assertEqual(preview["status"], "needs_confirmation")
        self.assertEqual(preview["data"]["count"], 1)
        self.assertEqual(preview["data"]["sample"], [str(target)])
        self.assertIn("Folders", preview["data"]["cascade"])
        self.assertTrue(Folder.objects.filter(pk=target.pk).exists())

        commit = self._tools().delete_objects(
            "filer_folder", object_ids=[str(target.pk)], confirmed=True
        )
        self.assertEqual(commit["status"], "ok")
        self.assertFalse(Folder.objects.filter(pk=target.pk).exists())
        self.assertTrue(Folder.objects.filter(pk=bystander.pk).exists())
        self.assertTrue(
            any("Deleted 1 Folder." in m["message"] for m in commit["messages"])
        )
