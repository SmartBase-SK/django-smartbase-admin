import json

from django import forms
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from django_smartbase_admin.admin.widgets import (
    PermissionGroup,
    SBAdminPermissionWidget,
)


class PermissionWidgetStaticTests(TestCase):
    def test_standard_codenames(self):
        self.assertTrue(SBAdminPermissionWidget._is_standard_codename("view_article"))
        self.assertTrue(SBAdminPermissionWidget._is_standard_codename("add_article"))
        self.assertTrue(SBAdminPermissionWidget._is_standard_codename("change_article"))
        self.assertTrue(SBAdminPermissionWidget._is_standard_codename("delete_article"))

    def test_custom_codenames(self):
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename("publish_article")
        )
        self.assertFalse(
            SBAdminPermissionWidget._is_standard_codename("moderate_comments")
        )
        self.assertFalse(SBAdminPermissionWidget._is_standard_codename("view"))

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

    def test_context_structure(self):
        widget = SBAdminPermissionWidget()
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
                        self.assertIn("view_testmodel", actions)
                        self.assertIn("add_testmodel", actions)
                        self.assertIn("change_testmodel", actions)
                        self.assertIn("delete_testmodel", actions)
                        custom = {p["codename"] for p in model["custom_perms"]}
                        self.assertIn("custom_action", custom)
                        found = True
                        break
            if found:
                break
        self.assertTrue(found, "Should find auth.permission model in context")

    def test_selected_values_preserved(self):
        widget = SBAdminPermissionWidget()
        perm = Permission.objects.get(codename="view_testmodel")
        selected_ids = [perm.pk]

        context = widget.get_context(
            "permissions", selected_ids, {"id": "id_permissions"}
        )
        stored = json.loads(context["widget"]["selected_values"])
        self.assertIn(perm.pk, stored)

    def test_selected_perm_has_selected_flag(self):
        widget = SBAdminPermissionWidget()
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
        widget = SBAdminPermissionWidget()
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


class PermissionWidgetRenderingTests(TestCase):
    def test_widget_render(self):
        class TestForm(forms.Form):
            permissions = forms.ModelMultipleChoiceField(
                queryset=Permission.objects.all(),
                widget=SBAdminPermissionWidget(),
            )

        form = TestForm()
        html = form.as_p()

        self.assertIn("permission-tree", html)
        self.assertIn("Search permissions", html)
        self.assertIn("permission-tree__body", html)
        self.assertIn("permission-tree__value", html)

    def test_widget_has_sbadmin_flag(self):
        widget = SBAdminPermissionWidget()
        self.assertTrue(widget.sb_admin_widget)

    def test_template_name_set(self):
        widget = SBAdminPermissionWidget()
        self.assertEqual(widget.template_name, "sb_admin/widgets/permission_tree.html")


class PermissionGroupTests(TestCase):
    """Tests for the groups-mode API (PermissionGroup DTO)."""

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

    def test_group_filters_by_model(self):
        """groups= with model= resolves to that content type's perms."""
        group = PermissionGroup(label="Test", model=Permission)
        widget = SBAdminPermissionWidget(groups=[group])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]

        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["app_verbose"], "Test")
        codenames = {p["codename"] for p in apps[0]["models"][0]["permissions"]}
        self.assertIn("view_testmodel", codenames)
        self.assertIn("add_testmodel", codenames)
        self.assertIn("change_testmodel", codenames)
        self.assertIn("delete_testmodel", codenames)
        self.assertIn("custom_action", codenames)

    def test_group_actions_filter(self):
        """actions= restricts which standard perms appear."""
        group = PermissionGroup(
            label="View & Add only",
            model=Permission,
            actions=("view", "add"),
        )
        widget = SBAdminPermissionWidget(groups=[group])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        perms = context["widget"]["permission_apps"][0]["models"][0]["permissions"]
        codenames = {p["codename"] for p in perms}
        self.assertIn("view_testmodel", codenames)
        self.assertIn("add_testmodel", codenames)
        self.assertNotIn("change_testmodel", codenames)
        self.assertNotIn("delete_testmodel", codenames)
        # custom_action has no standard prefix — still included if it matches
        # content type.  The actions filter only removes standard-action perms.
        self.assertIn("custom_action", codenames)

    def test_group_action_labels(self):
        """action_labels overrides standard perm display names."""
        group = PermissionGroup(
            label="Test",
            model=Permission,
            action_labels={"view": "See entries"},
        )
        widget = SBAdminPermissionWidget(groups=[group])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        perms = context["widget"]["permission_apps"][0]["models"][0]["permissions"]

        view_perm = next(p for p in perms if p["codename"] == "view_testmodel")
        self.assertEqual(view_perm["name"], "See entries")
        add_perm = next(p for p in perms if p["codename"] == "add_testmodel")
        self.assertEqual(add_perm["name"], "Can add test model")

    def test_group_help_text(self):
        """help_text is set on the app context."""
        group = PermissionGroup(
            label="Test",
            model=Permission,
            help_text="Controls test model access.",
        )
        widget = SBAdminPermissionWidget(groups=[group])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        self.assertEqual(
            context["widget"]["permission_apps"][0]["help_text"],
            "Controls test model access.",
        )

    def test_group_explicit_codenames(self):
        """codenames= list allows arbitrary permission selection."""
        view_perm = Permission.objects.get(codename="view_testmodel")
        custom_perm = Permission.objects.get(codename="custom_action")
        group = PermissionGroup(
            label="Custom",
            codenames=["view_testmodel", "custom_action"],
        )
        widget = SBAdminPermissionWidget(groups=[group])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        perms = context["widget"]["permission_apps"][0]["models"][0]["permissions"]
        ids = {p["id"] for p in perms}
        self.assertIn(view_perm.pk, ids)
        self.assertIn(custom_perm.pk, ids)
        self.assertEqual(len(ids), 2, "Only the two explicitly listed codenames")

    def test_group_selected_values_preserved(self):
        """Selected flags and hidden input respect the groups scope."""
        perm = Permission.objects.get(codename="view_testmodel")
        group = PermissionGroup(label="Test", model=Permission)
        widget = SBAdminPermissionWidget(groups=[group])

        context = widget.get_context("permissions", [perm.pk], {"id": "id_permissions"})
        stored = json.loads(context["widget"]["selected_values"])
        self.assertIn(perm.pk, stored)

        perms = context["widget"]["permission_apps"][0]["models"][0]["permissions"]
        view_p = next(p for p in perms if p["codename"] == "view_testmodel")
        self.assertTrue(view_p["selected"])
        add_p = next(p for p in perms if p["codename"] == "add_testmodel")
        self.assertFalse(add_p["selected"])

    def test_multiple_groups(self):
        """Multiple PermissionGroup entries create multiple app sections."""
        g1 = PermissionGroup(label="First", model=Permission)
        # Use User model for second group to get different content type
        from django.contrib.auth.models import User

        g2 = PermissionGroup(label="Second", model=User)
        widget = SBAdminPermissionWidget(groups=[g1, g2])
        context = widget.get_context("permissions", None, {"id": "id_permissions"})
        apps = context["widget"]["permission_apps"]
        self.assertEqual(len(apps), 2)
        self.assertEqual(apps[0]["app_verbose"], "First")
        self.assertEqual(apps[1]["app_verbose"], "Second")

    def test_groups_mode_render(self):
        """Rendered HTML includes help text and custom labels."""
        group = PermissionGroup(
            label="Test",
            model=Permission,
            help_text="Some help",
        )
        widget = SBAdminPermissionWidget(groups=[group])

        class TestForm(forms.Form):
            permissions = forms.ModelMultipleChoiceField(
                queryset=Permission.objects.all(),
                widget=widget,
            )

        html = TestForm().as_p()
        self.assertIn("permission-tree__help-text", html)
        self.assertIn("Some help", html)

    def test_value_from_datadict_filters_out_of_scope_ids(self):
        """Submitting IDs outside the defined groups is silently dropped."""
        view_perm = Permission.objects.get(codename="view_testmodel")
        add_perm = Permission.objects.get(codename="add_testmodel")
        # change_testmodel is NOT in the group (only view + add)
        change_perm = Permission.objects.get(codename="change_testmodel")

        group = PermissionGroup(
            label="Test",
            model=Permission,
            actions=("view", "add"),
        )
        widget = SBAdminPermissionWidget(groups=[group])

        data = {"perms": json.dumps([view_perm.pk, add_perm.pk, change_perm.pk])}
        result = widget.value_from_datadict(data, [], "perms")
        self.assertIn(view_perm.pk, result)
        self.assertIn(add_perm.pk, result)
        self.assertNotIn(
            change_perm.pk, result, "Out-of-scope permission should be filtered out"
        )

    def test_value_from_datadict_filters_ids_not_in_codenames(self):
        """When using codenames=, IDs not in that list are dropped."""
        view_perm = Permission.objects.get(codename="view_testmodel")
        custom_perm = Permission.objects.get(codename="custom_action")
        # add_testmodel is NOT in the explicit codename list
        add_perm = Permission.objects.get(codename="add_testmodel")

        group = PermissionGroup(
            label="Custom",
            codenames=["view_testmodel", "custom_action"],
        )
        widget = SBAdminPermissionWidget(groups=[group])

        data = {"perms": json.dumps([view_perm.pk, add_perm.pk, custom_perm.pk])}
        result = widget.value_from_datadict(data, [], "perms")
        self.assertIn(view_perm.pk, result)
        self.assertIn(custom_perm.pk, result)
        self.assertNotIn(
            add_perm.pk, result, "Permission outside codenames should be filtered out"
        )

    def test_value_from_datadict_default_mode_allows_all_ids(self):
        """Without groups, no filtering occurs."""
        view_perm = Permission.objects.get(codename="view_testmodel")
        change_perm = Permission.objects.get(codename="change_testmodel")

        widget = SBAdminPermissionWidget()  # no groups → default mode

        data = {"perms": json.dumps([view_perm.pk, change_perm.pk])}
        result = widget.value_from_datadict(data, [], "perms")
        self.assertIn(view_perm.pk, result)
        self.assertIn(change_perm.pk, result)
        self.assertEqual(len(result), 2)
