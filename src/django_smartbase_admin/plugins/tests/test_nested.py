"""Integration tests for :class:`TabulatorNestedPlugin`.

All tests drive admin-level entry points — ``view.action_list_json``
and ``view.get_tabulator_definition`` — against a real
``RequestFactory`` request, so the plugin is exercised end-to-end
through the same code path production uses.

``filer.Folder`` is the self-referential model (same shape as
``Category.parent`` in ``AGENTS.md``); it ships with the default
test settings so no custom app registration is needed.

The data-query path uses ``ArrayAgg`` which is Postgres-only, so
tests that consume the sliced page (``view.action_list_json``) are
marked ``@postgres_only``. The Tabulator-definition and config-
validation paths run on any backend.
"""

import json
from unittest import skipUnless
from unittest.mock import MagicMock

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import Q
from django.test import RequestFactory, TestCase, override_settings
from django.urls import path
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.plugins.nested import (
    TabulatorNestedPlugin,
    resolve_nested,
)
from django_smartbase_admin.services.views import SBAdminViewService


class FolderNestedAdmin(SBAdmin):
    """Test ModelAdmin wiring ``Folder`` (self-ref FK) with the plugin."""

    model = Folder
    list_display = ("id", "name")
    sbadmin_nested = {"parent_field": "parent"}


# Register once so ``sb_admin_site.urls`` can resolve the changelist /
# action endpoints for this admin. Tests override ``sbadmin_nested`` /
# restrict per-test; registration itself is shared.
if not sb_admin_site.is_registered(Folder):
    sb_admin_site.register(Folder, FolderNestedAdmin)

# Local URLconf so ``reverse("sb_admin:...")`` works inside tests.
urlpatterns = [path("sb-admin/", sb_admin_site.urls)]

postgres_only = skipUnless(
    connection.vendor == "postgresql",
    "Plugin data path uses ArrayAgg (Postgres-only).",
)


def build_list_request(user, model):
    """Build a ``RequestFactory`` request with the minimal
    ``request_data`` + configuration needed to run the list pipeline.
    Mirrors the audit tests' ``build_admin_request`` helper.
    """
    view_id = SBAdminViewService.get_model_path(model)
    request = RequestFactory().get(f"/sb-admin/{view_id}/")
    request.user = user
    request_data = SBAdminViewRequestData(
        view=view_id,
        action=None,
        modifier=None,
        user=user,
        request_get=request.GET,
        request_method="GET",
    )
    request_data.additional_data = {}
    config = MagicMock()
    config.restrict_queryset = lambda qs, **kwargs: qs
    config.apply_global_filter_to_queryset = lambda qs, *a, **kw: qs
    config.plugins = [TabulatorNestedPlugin]
    request_data.configuration = config
    request.request_data = request_data
    request.LANGUAGE_CODE = "en"
    return request


@override_settings(ROOT_URLCONF=__name__)
class TabulatorNestedPluginTests(TestCase):
    """End-to-end tests for the nested plugin driven through the
    admin's public entry points."""

    @classmethod
    def setUpTestData(cls):
        # Tree:
        #   root_a
        #     child_a1
        #     child_a2
        #       grandchild   ← must never surface as a top-level group
        #   root_b (lone root)
        cls.root_a = Folder.objects.create(name="root_a")
        cls.root_b = Folder.objects.create(name="root_b")
        cls.child_a1 = Folder.objects.create(name="child_a1", parent=cls.root_a)
        cls.child_a2 = Folder.objects.create(name="child_a2", parent=cls.root_a)
        cls.grandchild = Folder.objects.create(name="grandchild", parent=cls.child_a2)

    def _make_view_and_request(
        self, sbadmin_nested=FolderNestedAdmin.sbadmin_nested, restrict=None
    ):
        """Return ``(view, request)`` as ``SBAdminSite.initialize_admin_view``
        would produce before dispatching an action."""
        user = MagicMock(is_authenticated=True, is_superuser=True)
        request = build_list_request(user, Folder)
        if restrict is not None:
            request.request_data.configuration.restrict_queryset = restrict
        view = FolderNestedAdmin(Folder, sb_admin_site)
        view.sbadmin_nested = sbadmin_nested
        view.init_fields_cache(
            view.get_sbadmin_list_display(request),
            request.request_data.configuration,
        )
        return view, request

    def test_validation_rejects_bad_config(self):
        """One test covers the whole ``sbadmin_nested`` contract — no
        need for one assertion per permutation."""
        view = MagicMock(model=Folder)
        del view.get_sbadmin_nested

        view.sbadmin_nested = None
        self.assertIsNone(resolve_nested(view))

        view.sbadmin_nested = {"parent_field": "parent"}
        self.assertEqual(resolve_nested(view), {"parent_field": "parent"})

        bad_configs = [
            ({"element_column": "name"}, "parent_field"),
            ({"parent_field": "parent", "bogus": 1}, "unknown keys"),
            ({"parent_field": "nope"}, "does not exist"),
            ({"parent_field": "owner"}, "self-referential"),  # FK to User
        ]
        for cfg, expected_msg in bad_configs:
            view.sbadmin_nested = cfg
            with self.assertRaisesMessage(ImproperlyConfigured, expected_msg):
                resolve_nested(view)

    def test_tabulator_definition_enables_data_tree(self):
        """``view.get_tabulator_definition`` is the admin-level hook
        Tabulator consumes on page load. Plugin injects ``dataTree``
        options when ``sbadmin_nested`` is set, stays out of the way
        otherwise."""
        view, request = self._make_view_and_request()
        opts = view.get_tabulator_definition(request)["tabulatorOptions"]
        self.assertTrue(opts["dataTree"])
        self.assertEqual(opts["dataTreeChildField"], "_children")
        self.assertEqual(opts["dataTreeElementColumn"], "id")

        view, request = self._make_view_and_request(sbadmin_nested=None)
        opts = view.get_tabulator_definition(request)["tabulatorOptions"]
        self.assertNotIn("dataTree", opts)

    @postgres_only
    def test_action_list_json_paginates_by_parent_groups(self):
        """Full HTTP entry point ``view.action_list_json``:

        * ``last_row`` counts parent groups, not raw rows — the grand-
          child must not inflate it via ``COALESCE(parent, pk)``,
        * rows are assembled into a Tabulator tree; ``_children``
          holds the direct descendants only.
        """
        view, request = self._make_view_and_request()

        payload = json.loads(
            view.action_list_json(request, modifier="template").content
        )

        self.assertEqual(payload["last_row"], 2)
        ids = {row["id"] for row in payload["data"]}
        self.assertEqual(ids, {self.root_a.pk, self.root_b.pk})

        root_a_row = next(r for r in payload["data"] if r["id"] == self.root_a.pk)
        self.assertEqual(
            {c["id"] for c in root_a_row["_children"]},
            {self.child_a1.pk, self.child_a2.pk},
        )

    @postgres_only
    def test_action_list_json_respects_restrict_queryset_on_fk_parent(self):
        """``restrict_queryset`` must gate what can act as a parent,
        otherwise a child whose parent was filtered out would leak as
        a phantom root, inflate ``last_row``, and silently vanish when
        the page tried to render it."""
        view, request = self._make_view_and_request(
            restrict=lambda qs, **kwargs: qs.exclude(pk=self.root_a.pk)
        )

        payload = json.loads(
            view.action_list_json(request, modifier="template").content
        )

        self.assertEqual(payload["last_row"], 1)
        self.assertEqual([row["id"] for row in payload["data"]], [self.root_b.pk])

    @postgres_only
    def test_action_list_json_preserves_parent_group_order(self):
        """Parent groups should follow the active list ordering, not
        primary-key order and not any child-row sort values."""
        z_parent = Folder.objects.create(name="z_parent")
        a_parent = Folder.objects.create(name="a_parent")
        Folder.objects.create(name="aa_child", parent=z_parent)
        Folder.objects.create(name="zz_child", parent=a_parent)

        selected_ids = {z_parent.pk, a_parent.pk}
        view, request = self._make_view_and_request(
            restrict=lambda qs, **kwargs: qs.filter(
                Q(pk__in=selected_ids) | Q(parent_id__in=selected_ids)
            )
        )
        view.ordering = ("name",)

        payload = json.loads(
            view.action_list_json(request, modifier="template").content
        )

        self.assertEqual(
            [row["id"] for row in payload["data"]],
            [a_parent.pk, z_parent.pk],
        )

    @postgres_only
    def test_action_list_json_preserves_child_order_within_group(self):
        """Children under a parent should follow the active list ordering
        after hydration, not the database's default row order."""
        sort_parent = Folder.objects.create(name="sort_parent")
        z_child = Folder.objects.create(name="z_child", parent=sort_parent)
        a_child = Folder.objects.create(name="a_child", parent=sort_parent)

        selected_ids = {sort_parent.pk, z_child.pk, a_child.pk}
        view, request = self._make_view_and_request(
            restrict=lambda qs, **kwargs: qs.filter(pk__in=selected_ids)
        )
        view.ordering = ("name",)

        payload = json.loads(
            view.action_list_json(request, modifier="template").content
        )

        self.assertEqual([row["id"] for row in payload["data"]], [sort_parent.pk])
        self.assertEqual(
            [child["name"] for child in payload["data"][0]["_children"]],
            ["a_child", "z_child"],
        )

    @postgres_only
    def test_action_list_json_is_noop_without_sbadmin_nested(self):
        """Plugin is registered globally on the configuration, but only
        admins that opt in via ``sbadmin_nested`` get the tree
        behaviour — everyone else gets a normal flat list."""
        view, request = self._make_view_and_request(sbadmin_nested=None)

        payload = json.loads(
            view.action_list_json(request, modifier="template").content
        )

        self.assertEqual(payload["last_row"], Folder.objects.count())
        for row in payload["data"]:
            self.assertNotIn("_children", row)
