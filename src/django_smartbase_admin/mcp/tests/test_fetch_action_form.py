"""Tests for ``SBAdminTools.fetch_action_form`` on display-only modals.

Most modal actions open a form, and ``fetch_action_form`` returns that
form's field schema. But some modals override ``get()`` to render HTML
(a history / preview dialog) and carry no form. For those, the tool must
render the view and hand back the sanitized, whitespace-compacted HTML
instead of trying to introspect a non-existent form (which previously blew
up in ``issubclass(None, ...)``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from django import forms
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminBaseFormInit
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.actions import SBAdminRowAction
from django_smartbase_admin.engine.const import ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR
from django_smartbase_admin.engine.modal_view import RowActionModalView
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]

# Deliberately messy markup: template indentation + newlines to compact, a
# disallowed ``class`` / ``<script>`` to strip, and a ``<pre>`` block whose
# inner whitespace must be preserved.
_HISTORY_HTML = """
    <div class="modal">
        <h3>History</h3>
        <script>alert(1)</script>
        <pre>line 1
    line 2</pre>
    </div>
"""


class HistoryModalView(RowActionModalView):
    """Display-only modal: renders HTML in ``get()``, has no form."""

    modal_title = "Object History"

    def get(self, request, *args, **kwargs):
        return HttpResponse(_HISTORY_HTML)


class _ReparentForm(SBAdminBaseFormInit, forms.Form):
    parent = forms.ModelChoiceField(
        queryset=Folder.objects.all(),
        required=False,
        widget=SBAdminAutocompleteWidget(model=Folder, multiselect=False),
    )


class ReparentModalView(RowActionModalView):
    form_class = _ReparentForm
    modal_title = "Reparent"


class FolderActionFormTestAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name")
    sbadmin_fieldsets = ((None, {"fields": ("name",)}),)

    def get_sbadmin_row_actions(self, request):
        return [
            SBAdminRowAction(
                title="History",
                target_view=HistoryModalView,
                view=self,
            ),
            SBAdminRowAction(
                title="Reparent",
                target_view=ReparentModalView,
                view=self,
            ),
        ]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FetchActionFormHtmlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.folder = Folder.objects.create(name="alpha")
        cls.beta = Folder.objects.create(name="beta")
        cls.gamma = Folder.objects.create(name="gamma")

    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderActionFormTestAdmin)
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def test_formless_modal_returns_sanitized_compacted_html(self):
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))

        # Must not raise (previously: "issubclass() arg 1 must be a class").
        result = tools.fetch_action_form(
            "filer_folder", "HistoryModalView", object_id=str(self.folder.pk)
        )

        # Returns html, not a form-field schema.
        self.assertIn("html", result)
        self.assertNotIn("fields", result)
        self.assertEqual(result["title"], "Object History")

        html = result["html"]
        # Structure kept, presentational/executable stripped.
        self.assertIn("<h3>History</h3>", html)
        self.assertNotIn("class=", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("alert(1)", html)
        # <pre> inner formatting preserved verbatim.
        self.assertIn("line 1\n    line 2", html)
        # Outside the <pre> block, template newlines / indentation are gone
        # (single spaces between tags are fine; runs and newlines are not).
        outside_pre = html.replace("line 1\n    line 2", "")
        self.assertNotIn("\n", outside_pre)
        self.assertNotIn("  ", outside_pre)
        self.assertFalse(html.startswith(" ") or html.endswith(" "))

    def test_formless_modal_invisible_object_raises(self):
        """A form-less row modal must still enforce row visibility: an
        invisible/nonexistent object_id raises LookupError rather than
        leaking the rendered modal HTML."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))
        with self.assertRaises(LookupError):
            tools.fetch_action_form(
                "filer_folder", "HistoryModalView", object_id="99999999"
            )

    def test_action_form_autocomplete_widget_id_dispatches(self):
        """The action-scoped widget id must work directly with autocomplete."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        tools = SBAdminTools(request=build_mcp_request(user))

        form = tools.fetch_action_form(
            "filer_folder", "ReparentModalView", object_id=str(self.folder.pk)
        )
        widget_id = form["components"]["main"]["fields"]["parent"]["widget_id"]
        self.assertTrue(
            widget_id.startswith(
                "ReparentModalView" + ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR
            ),
            widget_id,
        )

        choices = tools.autocomplete("filer_folder", widget_id, search="beta")

        self.assertEqual(
            choices,
            [{"value": self.beta.pk, "label": str(self.beta)}],
        )
