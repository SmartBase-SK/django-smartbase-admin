import json

from django import forms
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from django_smartbase_admin.admin.widgets import (
    PermissionGroup,
    PermissionOption,
    SBAdminPermissionWidget,
)


class PermissionWidgetStaticTests(TestCase):
    def test_standard_codenames(self):
        self.assertTrue(
            SBAdminPermissionWidget._is_standard_codename("view_article", "article")
        )
        self.assertTrue(
            SBAdminPermissionWidget._is_standard_codename("add_article", "article")
        )
        self.assertTrue(
            SBAdminPermissionWidget._is_standard_codename("change_article", "article")
        )
        self.assertTrue(
            SBAdminPermissionWidget._is_standard_codename("delete_article", "article")
        )

    def test_custom_codenames(self):
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename("publish_article", "article")
        )
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename(
                "moderate_comments", "comment"
            )
        )
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename("view_dashboard", "account")
        )
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename("view", "article")
        )

    def test_standard_action(self):
        self.assertEqual(
            SBAdminPermissionWidget._standard_action("view_article"), "view"
        )
        self.assertEqual(
            SBAdminPermissionWidget._standard_action("change_article"), "change"
        )

    def test_parse_value_none(self):
        self.assertEqual(SBAdminPermissionWidget._parse_value(None), set())

    def test_parse_value_list(self):
        self.assertEqual(SBAdminPermissionWidget._parse_value([1, 2, 3]), {1, 2, 3})

    def test_parse_value_json_string(self):
        self.assertEqual(SBAdminPermissionWidget._parse_value("[1, 2, 3]"), {1, 2, 3})

    def test_parse_value_empty_string(self):
        self.assertEqual(SBAdminPermissionWidget._parse_value(""), set())

    def test_value_from_datadict(self):
        widget = SBAdminPermissionWidget()
        data = {"perms": json.dumps([1, 5, 9])}
        result = widget.value_from_datadict(data, [], "perms")
        self.assertEqual(result, [1, 5, 9])

    def test_value_from_datadict_empty(self):
        widget = SBAdminPermissionWidget()
        result = widget.value_from_datadict({}, [], "perms")
        self.assertEqual(result, [])


class PermissionWidgetContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ct = ContentType.objects.get_for_model(Permission)
        Permission.objects.get_or_create(
            content_type=ct,
            codename="view_testmodel",
            defaults={"name": "Can view test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="add_testmodel",
            defaults={"name": "Can add test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="change_testmodel",
            defaults={"name": "Can change test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="delete_testmodel",
            defaults={"name": "Can delete test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="custom_action",
            defaults={"name": "Can perform custom action"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="view_dashboard",
            defaults={"name": "Can view dashboard"},
        )

    def test_context_structure(self):
        widget = SBAdminPermissionWidget(queryset=Permission.objects.all())
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]

        self.assertGreater(len(apps), 0)

        found = False
        for app in apps:
            if app["app_label"] == "auth":
                for model in app["models"]:
                    if model["model_name"] == "permission":
                        self.assertIn("standard_perms_list", model)
                        self.assertIn("custom_perms", model)
                        self.assertIn("permissions", model)
                        actions = {p["codename"] for p in model["standard_perms_list"]}
                        self.assertIn("view_permission", actions)
                        self.assertIn("add_permission", actions)
                        self.assertIn("change_permission", actions)
                        self.assertIn("delete_permission", actions)
                        labels = {
                            p["codename"]: str(p["name"])
                            for p in model["standard_perms_list"]
                        }
                        self.assertEqual(labels["view_permission"], "View")
                        self.assertEqual(labels["add_permission"], "Create")
                        self.assertEqual(labels["change_permission"], "Edit")
                        self.assertEqual(labels["delete_permission"], "Delete")
                        custom = {p["codename"] for p in model["custom_perms"]}
                        self.assertIn("custom_action", custom)
                        self.assertIn("view_dashboard", custom)
                        self.assertIn("view_testmodel", custom)
                        found = True
                        break
            if found:
                break
        self.assertTrue(found, "Should find auth.permission model in context")

    def test_selected_values_preserved(self):
        widget = SBAdminPermissionWidget(queryset=Permission.objects.all())
        perm = Permission.objects.get(codename="view_testmodel")
        selected_ids = [perm.pk]

        context = widget.get_context(
            "permissions", selected_ids, {"id": "id_permissions"}
        )
        stored = json.loads(context["widget"]["selected_values"])
        self.assertIn(perm.pk, stored)

    def test_selected_perm_has_selected_flag(self):
        widget = SBAdminPermissionWidget(queryset=Permission.objects.all())
        perm = Permission.objects.get(codename="view_testmodel")

        context = widget.get_context("permissions", [perm.pk], {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]
        for app in apps:
            for model in app["models"]:
                for p in model["permissions"]:
                    if p["id"] == perm.pk:
                        self.assertTrue(p["selected"])
                    else:
                        self.assertFalse(p["selected"])

    def test_standard_perms_ordered(self):
        widget = SBAdminPermissionWidget(queryset=Permission.objects.all())
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]
        for app in apps:
            for model in app["models"]:
                names = [p["codename"] for p in model["standard_perms_list"] if p]
                # Standard perms should be grouped together but not necessarily all 4 exist
                # Just verify no custom perms leaked in
                for n in names:
                    self.assertTrue(
                        n.startswith(("view_", "add_", "change_", "delete_")),
                        f"{n} should be a standard permission",
                    )

    def test_auto_context_groups_multiple_models_under_app_label(self):
        article_ct, _ = ContentType.objects.get_or_create(
            app_label="catalog",
            model="article",
        )
        category_ct, _ = ContentType.objects.get_or_create(
            app_label="catalog",
            model="category",
        )
        Permission.objects.get_or_create(
            content_type=article_ct,
            codename="view_article",
            defaults={"name": "Can view article"},
        )
        Permission.objects.get_or_create(
            content_type=article_ct,
            codename="add_article",
            defaults={"name": "Can add article"},
        )
        Permission.objects.get_or_create(
            content_type=category_ct,
            codename="view_category",
            defaults={"name": "Can view category"},
        )

        widget = SBAdminPermissionWidget(
            queryset=Permission.objects.filter(content_type__app_label="catalog")
        )
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]

        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["app_label"], "catalog")
        self.assertEqual(apps[0]["app_verbose"], "Catalog")
        models = {model["model_name"]: model for model in apps[0]["models"]}
        self.assertEqual(set(models), {"article", "category"})
        self.assertEqual(
            {perm["codename"] for perm in models["article"]["standard_perms_list"]},
            {"view_article", "add_article"},
        )
        self.assertEqual(
            {perm["codename"] for perm in models["category"]["standard_perms_list"]},
            {"view_category"},
        )


class PermissionWidgetRenderingTests(TestCase):
    def test_widget_render(self):
        class TestForm(forms.Form):
            permissions = forms.ModelMultipleChoiceField(
                queryset=Permission.objects.all(),
                widget=SBAdminPermissionWidget(),
            )

        form = TestForm()
        html = form.as_p()

        self.assertIn("Search permissions", html)
        self.assertIn('class="input"', html)
        self.assertIn("data-permission-tree", html)
        self.assertIn("data-permission-tree-value", html)
        self.assertIn("data-permission-tree-checkbox", html)
        self.assertIn('class="toggle"', html)
        self.assertIn('data-bs-toggle="collapse"', html)
        self.assertIn("collapse show", html)

    def test_widget_has_sbadmin_flag(self):
        widget = SBAdminPermissionWidget()
        self.assertTrue(widget.sb_admin_widget)

    def test_template_name_set(self):
        widget = SBAdminPermissionWidget()
        self.assertEqual(widget.template_name, "sb_admin/widgets/permission_tree.html")


class PermissionGroupTests(TestCase):
    """Tests for the explicit business-group API."""

    @classmethod
    def setUpTestData(cls):
        ct = ContentType.objects.get_for_model(Permission)
        Permission.objects.get_or_create(
            content_type=ct,
            codename="view_testmodel",
            defaults={"name": "Can view test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="add_testmodel",
            defaults={"name": "Can add test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="change_testmodel",
            defaults={"name": "Can change test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="delete_testmodel",
            defaults={"name": "Can delete test model"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="custom_action",
            defaults={"name": "Can perform custom action"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="view_dashboard",
            defaults={"name": "Can view dashboard"},
        )
        Permission.objects.get_or_create(
            content_type=ct,
            codename="view_dashboard",
            defaults={"name": "Can view dashboard"},
        )

    def _context_for_queryset(self, queryset, groups=None, value=None):
        field = forms.ModelMultipleChoiceField(
            queryset=queryset,
            widget=SBAdminPermissionWidget(groups=groups),
        )
        return field.widget.get_context(
            "permissions",
            value,
            {"id": "id_permissions"},
        )

    def test_groups_none_keeps_automatic_queryset_grouping(self):
        ct = ContentType.objects.get_for_model(Permission)
        context = self._context_for_queryset(
            Permission.objects.filter(content_type=ct),
            groups=None,
        )
        apps = context["widget"]["permission_apps"]

        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["app_label"], "auth")
        self.assertEqual(
            str(apps[0]["app_verbose"]),
            "Authentication and Authorization",
        )
        self.assertEqual(apps[0]["options"], [])
        codenames = {p["codename"] for p in apps[0]["models"][0]["permissions"]}
        self.assertIn("view_testmodel", codenames)
        self.assertIn("custom_action", codenames)

    def test_groups_mode_builds_visible_options_from_strict_refs(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        groups = [
            PermissionGroup(
                label="Packages",
                help_text="Controls package workflows.",
                options=[
                    PermissionOption(
                        label="Create package",
                        help_text="Allows creating packages with dependencies.",
                        codenames=[
                            "auth.permission:add_testmodel",
                            "auth.permission:view_testmodel",
                        ],
                    )
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(pk__in=[view_perm.pk, add_perm.pk]),
            groups=groups,
            value=[],
        )
        app = context["widget"]["permission_apps"][0]
        option = app["options"][0]

        self.assertEqual(app["app_verbose"], "Packages")
        self.assertEqual(app["help_text"], "Controls package workflows.")
        self.assertEqual(app["models"], [])
        self.assertEqual(option["name"], "Create package")
        self.assertEqual(
            option["help_text"],
            "Allows creating packages with dependencies.",
        )
        self.assertEqual(set(option["permission_ids"]), {view_perm.pk, add_perm.pk})
        self.assertFalse(option["selected"])
        self.assertFalse(option["indeterminate"])

    def test_groups_mode_appends_unseen_permissions_grouped_by_app_label(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        custom_perm = Permission.objects.get(codename="custom_action")
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="View packages",
                        codenames=["auth.permission:view_testmodel"],
                    )
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(
                pk__in=[view_perm.pk, add_perm.pk, custom_perm.pk]
            ),
            groups=groups,
        )
        apps = context["widget"]["permission_apps"]
        leftover_ids = {
            permission["id"]
            for app in apps[1:]
            for model in app["models"]
            for permission in model["permissions"]
        }

        self.assertEqual(apps[0]["app_verbose"], "Packages")
        self.assertEqual(apps[1]["app_label"], "auth")
        self.assertEqual(
            str(apps[1]["app_verbose"]),
            "Authentication and Authorization",
        )
        self.assertNotIn(view_perm.pk, leftover_ids)
        self.assertIn(add_perm.pk, leftover_ids)
        self.assertIn(custom_perm.pk, leftover_ids)

    def test_groups_mode_appends_unseen_models_under_app_label(self):
        parcel_ct, _ = ContentType.objects.get_or_create(
            app_label="warehouse",
            model="parcel",
        )
        shipment_ct, _ = ContentType.objects.get_or_create(
            app_label="warehouse",
            model="shipment",
        )
        view_parcel, _ = Permission.objects.get_or_create(
            content_type=parcel_ct,
            codename="view_parcel",
            defaults={"name": "Can view parcel"},
        )
        add_parcel, _ = Permission.objects.get_or_create(
            content_type=parcel_ct,
            codename="add_parcel",
            defaults={"name": "Can add parcel"},
        )
        view_shipment, _ = Permission.objects.get_or_create(
            content_type=shipment_ct,
            codename="view_shipment",
            defaults={"name": "Can view shipment"},
        )
        groups = [
            PermissionGroup(
                label="Parcel workflows",
                options=[
                    PermissionOption(
                        label="View parcels",
                        codenames=["warehouse.parcel:view_parcel"],
                    )
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(
                pk__in=[view_parcel.pk, add_parcel.pk, view_shipment.pk]
            ),
            groups=groups,
        )
        apps = context["widget"]["permission_apps"]
        models = {model["model_name"]: model for model in apps[1]["models"]}

        self.assertEqual(apps[0]["app_verbose"], "Parcel workflows")
        self.assertEqual(apps[1]["app_label"], "warehouse")
        self.assertEqual(apps[1]["app_verbose"], "Warehouse")
        self.assertEqual(set(models), {"parcel", "shipment"})
        self.assertEqual(
            {perm["codename"] for perm in models["parcel"]["standard_perms_list"]},
            {"add_parcel"},
        )
        self.assertEqual(
            {perm["codename"] for perm in models["shipment"]["standard_perms_list"]},
            {"view_shipment"},
        )

    def test_groups_mode_does_not_duplicate_permissions_used_by_multiple_options(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="View packages",
                        codenames=["auth.permission:view_testmodel"],
                    ),
                    PermissionOption(
                        label="Create package",
                        codenames=[
                            "auth.permission:add_testmodel",
                            "auth.permission:view_testmodel",
                        ],
                    ),
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(pk__in=[view_perm.pk, add_perm.pk]),
            groups=groups,
        )
        leftover_ids = {
            permission["id"]
            for app in context["widget"]["permission_apps"][1:]
            for model in app["models"]
            for permission in model["permissions"]
        }

        self.assertEqual(leftover_ids, set())

    def test_group_option_is_selected_when_all_backing_permissions_selected(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="Create package",
                        codenames=[
                            "auth.permission:add_testmodel",
                            "auth.permission:view_testmodel",
                        ],
                    )
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(pk__in=[view_perm.pk, add_perm.pk]),
            groups=groups,
            value=[view_perm.pk, add_perm.pk],
        )
        option = context["widget"]["permission_apps"][0]["options"][0]

        self.assertTrue(option["selected"])
        self.assertFalse(option["indeterminate"])

    def test_group_option_is_indeterminate_when_some_backing_permissions_selected(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="Create package",
                        codenames=[
                            "auth.permission:add_testmodel",
                            "auth.permission:view_testmodel",
                        ],
                    )
                ],
            )
        ]

        context = self._context_for_queryset(
            Permission.objects.filter(pk__in=[view_perm.pk, add_perm.pk]),
            groups=groups,
            value=[view_perm.pk],
        )
        option = context["widget"]["permission_apps"][0]["options"][0]

        self.assertFalse(option["selected"])
        self.assertTrue(option["indeterminate"])
        self.assertEqual(json.loads(option["selected_ids_json"]), [view_perm.pk])

    def test_groups_mode_rejects_malformed_permission_refs(self):
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="Create package",
                        codenames=["add_testmodel"],
                    )
                ],
            )
        ]

        with self.assertRaises(ImproperlyConfigured):
            self._context_for_queryset(Permission.objects.all(), groups=groups)

    def test_groups_mode_rejects_empty_option_refs(self):
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="Create package",
                        codenames=[],
                    )
                ],
            )
        ]

        with self.assertRaises(ImproperlyConfigured):
            self._context_for_queryset(Permission.objects.all(), groups=groups)

    def test_groups_mode_rejects_refs_missing_from_queryset(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        groups = [
            PermissionGroup(
                label="Packages",
                options=[
                    PermissionOption(
                        label="Create package",
                        codenames=["auth.permission:add_testmodel"],
                    )
                ],
            )
        ]

        with self.assertRaises(ImproperlyConfigured):
            self._context_for_queryset(
                Permission.objects.filter(pk=view_perm.pk),
                groups=groups,
            )

    def test_explicit_queryset_is_used_for_unattached_widget(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        widget = SBAdminPermissionWidget(
            queryset=Permission.objects.filter(pk=view_perm.pk),
            groups=[
                PermissionGroup(
                    label="Custom",
                    options=[
                        PermissionOption(
                            label="View test model",
                            codenames=["auth.permission:view_testmodel"],
                        )
                    ],
                )
            ],
        )

        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        option = context["widget"]["permission_apps"][0]["options"][0]

        self.assertEqual(option["permission_ids"], [view_perm.pk])

    def test_groups_mode_render(self):
        group = PermissionGroup(
            label="Test",
            help_text="Some help",
            options=[
                PermissionOption(
                    label="View test model",
                    help_text="Option help",
                    codenames=["auth.permission:view_testmodel"],
                )
            ],
        )
        widget = SBAdminPermissionWidget(groups=[group])

        class TestForm(forms.Form):
            permissions = forms.ModelMultipleChoiceField(
                queryset=Permission.objects.all(),
                widget=widget,
            )

        html = TestForm().as_p()
        self.assertIn("Some help", html)
        self.assertIn("data-permission-tree-checkbox", html)
        self.assertIn("Option help", html)

    def test_value_from_datadict_default_mode_allows_all_ids(self):
        view_perm = Permission.objects.get(codename="view_testmodel")
        change_perm = Permission.objects.get(codename="change_testmodel")

        widget = SBAdminPermissionWidget()

        data = {"perms": json.dumps([view_perm.pk, change_perm.pk])}
        result = widget.value_from_datadict(data, [], "perms")
        self.assertIn(view_perm.pk, result)
        self.assertIn(change_perm.pk, result)
        self.assertEqual(len(result), 2)
