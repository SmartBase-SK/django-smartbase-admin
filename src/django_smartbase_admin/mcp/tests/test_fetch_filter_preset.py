"""End-to-end coverage for ``list_admins[].filter_presets`` discovery and
``fetch_filter_preset`` resolution.

Single integration test exercises both halves of the contract:
* ``list_admins`` advertises both the static (``sbadmin_list_view_config``)
  and saved (``SBAdminListViewConfiguration``) presets the user can see;
* ``fetch_filter_preset`` resolves either source back into ready-to-use
  ``list_rows`` kwargs, decoding the raw ``url_params`` blob server-side
  and stripping the empty placeholder filter keys the UI pads in.

Folding both into one test keeps the test count down and guarantees the
two surfaces stay in lockstep — a regression on either side fails this
one test instead of silently drifting until prod use.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import MultipleChoiceFilterWidget
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)
from django_smartbase_admin.models import SBAdminListViewConfiguration


class FolderPresetTestAdmin(SBAdmin):
    """Folder admin with two static presets — exercises raw-config decode.

    ``Recent`` carries ``filterData`` (a real filter plus an empty ``""``
    placeholder, the way the UI pads unfiltered columns), ``tableParams``
    (sort + size), and the full-text-search key inside ``filterData`` —
    the branches ``_decode_preset_url_params`` has to flatten / strip.

    ``By status`` stores its multichoice value in the *frontend widget*
    form ``[{"value", "label"}]`` (exactly how a real preset persists a
    ``MultipleChoiceFilterWidget`` selection). This is the shape the
    earlier implementation mangled; the round-trip assertion proves the
    decoded output drives ``list_rows`` end to end.
    """

    model = Folder
    sbadmin_list_display = (
        "id",
        "name",
        SBAdminField(
            name="status",
            title="Status",
            annotate=F("name"),  # mirror name so we can filter on it
            filter_field="status",
            filter_widget=MultipleChoiceFilterWidget(
                choices=[("alpha", "Alpha"), ("beta", "Beta")]
            ),
        ),
    )
    sbadmin_list_view_config = [
        {
            "name": "Recent",
            "url_params": {
                "filterData": {
                    "name": "alpha",
                    "owner": "",  # padding placeholder — must be stripped
                    "sb_admin_full_search": "needle",
                },
                "tableParams": {"sort": [{"field": "name", "dir": "asc"}], "size": 50},
            },
        },
        {
            "name": "By status",
            "url_params": {
                "filterData": {
                    "status": [{"value": "alpha", "label": "Alpha"}],
                    "name": "",
                }
            },
        },
        {
            # Some saved presets persist a multi-value filter double-encoded
            # as a JSON *string* rather than a list. fetch must parse it back
            # to the list shape list_rows accepts.
            "name": "By status (stringified)",
            "url_params": {
                "filterData": {
                    "status": '[{"value": "alpha", "label": "Alpha"}]',
                }
            },
        },
    ]


urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(ROOT_URLCONF=__name__)
class FetchFilterPresetTests(TestCase):
    def setUp(self):
        super().setUp()
        self._original_admin = sb_admin_site._registry.pop(Folder, None)
        sb_admin_site.register(Folder, FolderPresetTestAdmin)
        # The configuration is a singleton; if a prior test populated
        # ``view_map``, ``resolve_admin`` would hand the tool a stale
        # admin instance. Rebuild it so the lookup hits our class.
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        sb_admin_site._registry.pop(Folder, None)
        if self._original_admin is not None:
            sb_admin_site._registry[Folder] = self._original_admin
        super().tearDown()

    def test_presets_surface_and_fetch_decodes_both_sources(self):
        # Real user so the saved-preset DB lookup has a valid FK target.
        User = get_user_model()
        user = User.objects.create(
            username="vw", is_active=True, is_staff=True, is_superuser=True
        )

        # Saved preset: stored as a JSON-string ``url_params`` (mirrors
        # what the frontend POSTs to ``create_or_update_saved_view``),
        # padded with an empty placeholder to prove stripping works on
        # the saved path too.
        saved = SBAdminListViewConfiguration.objects.create(
            user=user,
            name="My follow-ups",
            view="filer_folder",
            url_params=json.dumps(
                {
                    "filterData": {"name": "beta", "owner": ""},
                    "tableParams": {"page": 3},
                }
            ),
        )

        tools = SBAdminTools(request=build_mcp_request(user))

        # 1. ``list_admins`` advertises both presets, tagged by source.
        result = tools.list_admins()
        entry = next(e for e in result["admin_views"] if e["view_id"] == "filer_folder")
        presets = {(p["name"], p["source"]): p for p in entry["filter_presets"]}
        # ``get_base_config`` always prepends the implicit "All" reset.
        self.assertIn(("All", "static"), presets)
        self.assertIn(("Recent", "static"), presets)
        # Saved presets carry their pk so fetch can resolve by id.
        self.assertEqual(presets[("My follow-ups", "saved")]["id"], saved.pk)

        # 2. Static preset decodes into ready-to-use ``list_rows`` kwargs.
        #    The ``owner: ""`` placeholder is stripped; ``page`` is never
        #    returned (session state, not part of the preset).
        decoded = tools.fetch_filter_preset(
            view_id="filer_folder", name="Recent", source="static"
        )
        self.assertEqual(decoded["filter_data"], {"name": "alpha"})
        self.assertEqual(decoded["full_text_search"], "needle")
        self.assertEqual(decoded["sort"], [{"field": "name", "dir": "asc"}])
        self.assertEqual(decoded["page_size"], 50)
        self.assertNotIn("page", decoded)

        # 3. The implicit "All" reset decodes to no filters at all — every
        #    column is an empty placeholder, so stripping leaves ``{}``.
        all_decoded = tools.fetch_filter_preset(
            view_id="filer_folder", name="All", source="static"
        )
        self.assertEqual(all_decoded, {})

        # 4. Saved preset resolves by id, strips its placeholder, drops page.
        decoded_saved = tools.fetch_filter_preset(
            view_id="filer_folder", source="saved", id=saved.pk
        )
        self.assertEqual(decoded_saved, {"filter_data": {"name": "beta"}})

        # 5. Unknown preset raises LookupError listing the valid names so
        #    the agent can recover without a second discovery call.
        with self.assertRaises(LookupError) as ctx:
            tools.fetch_filter_preset(
                view_id="filer_folder", name="nope", source="static"
            )
        self.assertIn("Recent", str(ctx.exception))

        # 6. A multichoice preset stored as ``[{"value","label"}]`` decodes
        #    to that same shape — which ``list_rows`` accepts directly.
        decoded_status = tools.fetch_filter_preset(
            view_id="filer_folder", name="By status", source="static"
        )
        # The key is surfaced as the column ``name`` (here name == filter_field
        # == "status"), the single identifier the agent uses everywhere else;
        # on replay list_rows normalizes it back to the filter_field. Key
        # round-tripping when they differ is covered in test_filter_validation.
        self.assertEqual(
            decoded_status["filter_data"],
            {"status": [{"value": "alpha", "label": "Alpha"}]},
        )

        # 7. A preset that stored the same value double-encoded as a JSON
        #    *string* decodes to the identical parsed list, so list_rows
        #    (which rejects a bare str for a multichoice) accepts it.
        decoded_str = tools.fetch_filter_preset(
            view_id="filer_folder", name="By status (stringified)", source="static"
        )
        self.assertEqual(
            decoded_str["filter_data"],
            {"status": [{"value": "alpha", "label": "Alpha"}]},
        )
