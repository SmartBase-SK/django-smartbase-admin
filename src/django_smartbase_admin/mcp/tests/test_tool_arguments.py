"""Tool argument schemas: descriptions that survive client truncation and
shape validation shared by the MCP and REST transports."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from filer.models import Folder
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from pydantic import ValidationError
from rest_framework.test import APIRequestFactory

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.mcp.instructions import SBADMIN_MCP_SERVER_INSTRUCTIONS
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.rest import (
    SBAdminMCPRestAuthenticator,
    SBAdminMCPToolAPIView,
    is_guarded_mcp_tool,
)
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)
from django_smartbase_admin.mcp.tool_arguments import validate_tool_arguments

# Claude Code keeps this many characters of a tool description and of the
# server instructions; the rest is cut off.
CLIENT_DESCRIPTION_LIMIT = 2048


def _published_length(doc: str | None) -> int:
    """Length of ``doc`` as FastMCP publishes it on Python 3.12, where the
    method docstring keeps its 8-space indentation. Python 3.13 strips that
    indentation at compile time, so measuring ``len(__doc__)`` there would
    pass docstrings that are too long on 3.12."""
    lines = inspect.cleandoc(doc or "").splitlines()
    # Every non-empty line after the first, and the closing quotes' line.
    indented = sum(1 for line in lines[1:] if line) + 1
    return sum(len(line) + 1 for line in lines) + 8 * indented


def _tools():
    user = MagicMock(is_active=True, is_staff=True, is_authenticated=True)
    return SBAdminTools(request=build_mcp_request(user))


def _guarded_methods():
    tools = _tools()
    return {
        name: method
        for name, method in inspect.getmembers(tools, predicate=inspect.ismethod)
        if is_guarded_mcp_tool(method)
    }


class ToolDescriptionTests(SimpleTestCase):
    def test_tool_descriptions_fit_client_limit(self):
        for name, method in _guarded_methods().items():
            with self.subTest(tool=name):
                self.assertLessEqual(
                    _published_length(method.__doc__), CLIENT_DESCRIPTION_LIMIT
                )

    def test_server_instructions_fit_client_limit(self):
        self.assertLessEqual(
            len(SBADMIN_MCP_SERVER_INSTRUCTIONS), CLIENT_DESCRIPTION_LIMIT
        )

    def test_every_argument_is_described_in_the_schema(self):
        for name, method in _guarded_methods().items():
            schema = func_metadata(method).arg_model.model_json_schema()
            for arg, prop in schema.get("properties", {}).items():
                with self.subTest(tool=name, arg=arg):
                    self.assertTrue(prop.get("description"))

    def test_list_rows_schema_spells_out_nested_shapes(self):
        schema = func_metadata(_tools().list_rows).arg_model.model_json_schema()
        defs = schema["$defs"]

        self.assertEqual(
            defs["AggregateSpec"]["properties"]["fn"]["enum"],
            ["sum", "avg", "min", "max", "count"],
        )
        self.assertEqual(defs["SortSpec"]["properties"]["dir"]["enum"], ["asc", "desc"])
        for spec in ("AggregateSpec", "SortSpec", "InlineSpec"):
            self.assertIs(defs[spec]["additionalProperties"], False)
        self.assertEqual(schema["properties"]["fields"]["minItems"], 1)


class ToolArgumentValidationTests(SimpleTestCase):
    base = {"view_id": "filer_folder", "fields": ["id", "name"]}

    def _validate(self, tool, **arguments):
        return validate_tool_arguments(getattr(_tools(), tool), arguments)

    def assertRejected(self, tool, **arguments):
        with self.assertRaises(ValidationError):
            self._validate(tool, **arguments)

    def test_valid_call_fills_defaults(self):
        kwargs = self._validate(
            "list_rows", **self.base, sort=[{"field": "name", "dir": "desc"}]
        )

        self.assertEqual(kwargs["sort"], [{"field": "name", "dir": "desc"}])
        self.assertEqual(kwargs["page"], 1)
        self.assertIsNone(kwargs["aggregate"])

    def test_stringified_json_arguments_are_parsed(self):
        kwargs = self._validate("list_rows", **self.base, aggregate='[{"fn": "count"}]')

        self.assertEqual(kwargs["aggregate"], [{"fn": "count"}])

    # Malformed list_rows / list_admins arguments are tested next to each
    # feature (sort, aggregate, include_inlines, fields, detail) through
    # ``call_mcp_tool``. The cases below have no feature test of their own.

    def test_enumerated_arguments(self):
        self.assertRejected("fetch_filter_preset", view_id="filer_folder", source="x")

    def test_object_ids_must_be_non_empty(self):
        self.assertRejected("delete_objects", view_id="filer_folder", object_ids=[])
        self.assertRejected(
            "invoke_selection_action",
            view_id="filer_folder",
            action_id="a",
            object_ids=[],
        )

    def test_unknown_argument_is_a_type_error(self):
        with self.assertRaises(TypeError):
            self._validate("list_admins", detial="index")


class _StaffAuthenticator(SBAdminMCPRestAuthenticator):
    def authenticate(self, request, **kwargs):
        return MagicMock(
            is_active=True, is_staff=True, is_superuser=True, is_authenticated=True
        )


class _FolderAdmin(SBAdmin):
    model = Folder
    sbadmin_list_display = ("id", "name", "parent", "children")


# Every malformed shape the schema now rejects. Before the schema, each of
# these had a hand-written check; without one the tool would hit a KeyError
# or AttributeError, which the REST view would turn into a 500.
MALFORMED_CALLS = [
    ("list_rows", {"view_id": "filer_folder", "fields": []}, "fields"),
    (
        "list_rows",
        {"view_id": "filer_folder", "fields": ["name"], "sort": ["name"]},
        "sort.0",
    ),
    (
        "list_rows",
        {"view_id": "filer_folder", "fields": ["name"], "sort": [{"field": "name"}]},
        "sort.0.dir",
    ),
    (
        "list_rows",
        {
            "view_id": "filer_folder",
            "fields": ["name"],
            "sort": [{"field": "name", "dir": "up"}],
        },
        "sort.0.dir",
    ),
    (
        "list_rows",
        {
            "view_id": "filer_folder",
            "fields": ["name"],
            "aggregate": [{"fn": "median"}],
        },
        "aggregate.0.fn",
    ),
    (
        "list_rows",
        {"view_id": "filer_folder", "fields": ["name"], "aggregate": ["count"]},
        "aggregate.0",
    ),
    (
        "list_rows",
        {
            "view_id": "filer_folder",
            "fields": ["name"],
            "aggregate": [{"function": "sum", "field": "id"}],
        },
        "aggregate.0.function",
    ),
    (
        "list_rows",
        {
            "view_id": "filer_folder",
            "fields": ["name"],
            "aggregate": [{"fn": "count"}],
            "group_by": "name",
        },
        "group_by",
    ),
    (
        "list_rows",
        {"view_id": "filer_folder", "fields": ["name"], "include_inlines": ["I"]},
        "include_inlines.0",
    ),
    (
        "list_rows",
        {
            "view_id": "filer_folder",
            "fields": ["name"],
            "include_inlines": [{"inline_name": "I"}],
        },
        "include_inlines.0.fields",
    ),
    ("list_admins", {"detail": "everything"}, "detail"),
    ("fetch_filter_preset", {"view_id": "filer_folder", "source": "x"}, "source"),
    ("delete_objects", {"view_id": "filer_folder", "object_ids": []}, "object_ids"),
    (
        "invoke_selection_action",
        {"view_id": "filer_folder", "action_id": "a", "object_ids": []},
        "object_ids",
    ),
]


urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class RestArgumentValidationTests(TestCase):
    """Runs against a real admin with a row, so a call that slipped past the
    schema would reach the tool code instead of stopping at an unknown
    ``view_id``."""

    def setUp(self):
        super().setUp()
        self._original = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, _FolderAdmin)
        MCPToolTestConfig().init_view_map()
        Folder.objects.create(name="alpha")

    def tearDown(self):
        sb_admin_site._registry.pop(Folder, None)
        if self._original is not None:
            sb_admin_site._registry[Folder] = self._original
        super().tearDown()

    def test_malformed_calls_are_400_not_500(self):
        view = SBAdminMCPToolAPIView.as_view(authenticator=_StaffAuthenticator())

        for tool_name, arguments, loc in MALFORMED_CALLS:
            with self.subTest(tool=tool_name, loc=loc):
                request = APIRequestFactory().post(
                    f"/mcp/rest/tools/{tool_name}/", arguments, format="json"
                )

                response = view(request, tool_name=tool_name)

                self.assertEqual(response.status_code, 400)
                self.assertIn(f"{loc}\n", response.data["detail"])

    def test_unknown_argument_is_400(self):
        view = SBAdminMCPToolAPIView.as_view(authenticator=_StaffAuthenticator())
        request = APIRequestFactory().post(
            "/mcp/rest/tools/list_admins/", {"detial": "index"}, format="json"
        )

        response = view(request, tool_name="list_admins")

        self.assertEqual(response.status_code, 400)
        self.assertIn("detial", response.data["detail"])
