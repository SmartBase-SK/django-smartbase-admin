"""Parent-dependent inline modals require access to the parent object."""

from django import forms
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase, override_settings
from django.urls import path
from filer.models import File, Folder

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import SBAdminSite
from django_smartbase_admin.engine.actions import SBAdminFormViewAction
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.engine.modal_view import ActionModalView, RowActionModalView
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.mcp.actions import SBAdminMCPActionFormService


class RenameForm(forms.Form):
    name = forms.CharField()


class RenameFolderFilesModal(ActionModalView):
    form_class = RenameForm

    def process_form_valid(self, request, form):
        File.objects.filter(folder=self.view.parent_instance).update(
            name=form.cleaned_data["name"]
        )
        return super().process_form_valid(request, form)


class RenameFileModal(RowActionModalView):
    form_class = RenameForm

    def process_form_valid_object(self, request, form, obj):
        obj.name = form.cleaned_data["name"]
        obj.save()


class PermissionFileInline(SBAdminTableInline):
    model = File
    fk_name = "folder"
    fields = ("name",)

    def get_sbadmin_inline_list_actions(self, request):
        return [
            SBAdminFormViewAction(
                title="Rename file", target_view=RenameFileModal, view=self
            )
        ]

    def get_sbadmin_fieldsets(self, request, object_id=None):
        if self.parent_instance is None:
            return []
        return [
            (
                None,
                {
                    "fields": ("name",),
                    "actions": [
                        SBAdminFormViewAction(
                            title="Rename folder files",
                            target_view=RenameFolderFilesModal,
                            view=self,
                        )
                    ],
                },
            )
        ]


class PermissionFolderAdmin(SBAdmin):
    sbadmin_list_display = ("name",)
    sbadmin_fieldsets = ((None, {"fields": ("name",)}),)
    inlines = [PermissionFileInline]

    def has_view_or_change_permission(self, request, obj=None):
        if obj is not None and obj.name == "Restricted":
            return False
        return super().has_view_or_change_permission(request, obj)


class InlinePermissionRoleConfiguration(SBAdminRoleConfiguration):
    pass


class InlinePermissionConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = InlinePermissionRoleConfiguration()
        parent_admin = test_admin_site._registry[Folder]
        parent_admin.init_view_static(configuration, Folder, test_admin_site)
        configuration.default_view = SBAdminMenuItem(view_id=parent_admin.get_id())
        return configuration


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(User, UserAdmin)
test_admin_site.register(Folder, PermissionFolderAdmin)

urlpatterns = [path("sb-admin/", test_admin_site.urls)]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=f"{__name__}.InlinePermissionConfiguration",
)
class InlineActionPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.folder = Folder.objects.create(pk=7, name="Folder")
        # Keep the row ID distinct from the parent ID used by fieldset actions.
        cls.file = File.objects.create(pk=19, folder=cls.folder, name="original.txt")
        cls.user = User.objects.create_user(username="file-editor", is_staff=True)

    def setUp(self):
        self.grant_permissions("view_file", "change_file")
        self.client.force_login(self.user)
        self.inline = PermissionFileInline(Folder, test_admin_site)
        self.fieldset_url = self.inline.get_action_url(
            "RenameFolderFilesModal", object_id=self.folder.pk
        )

    def grant_permissions(self, *codenames):
        self.user.user_permissions.set(
            Permission.objects.filter(
                content_type__app_label="filer", codename__in=codenames
            )
        )
        self.user = User.objects.get(pk=self.user.pk)

    def find_modal(self, modal, object_id):
        request = RequestFactory().get("/")
        request.user = self.user
        request.session = {}
        request_data = SBAdminViewRequestData.from_request_and_kwargs(
            request,
            view=self.inline.get_id(),
            action=modal.__name__,
            modifier="template",
        )
        view = request_data.selected_view
        view.init_view_dynamic(request, request_data)
        return SBAdminMCPActionFormService._find_modal_action(
            view, modal.__name__, request, object_id=str(object_id)
        )

    def assert_fieldset_modal_unavailable(self):
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.fieldset_url, {"name": "must-not-save.txt"}
                )
                self.assertEqual(response.status_code, 404)
        with self.assertRaises(LookupError):
            self.find_modal(RenameFolderFilesModal, self.folder.pk)
        self.file.refresh_from_db()
        self.assertEqual(self.file.name, "original.txt")

    def test_fieldset_modal_requires_parent_permission(self):
        self.assertFalse(self.user.has_perm("filer.view_folder"))
        self.assertFalse(self.user.has_perm("filer.change_folder"))

        self.assert_fieldset_modal_unavailable()

    def test_parent_view_or_change_permission_allows_child_action(self):
        for parent_permission in ("view_folder", "change_folder"):
            with self.subTest(parent_permission=parent_permission):
                self.grant_permissions("view_file", "change_file", parent_permission)

                self.assertEqual(self.client.get(self.fieldset_url).status_code, 200)
                response = self.client.post(self.fieldset_url, {"name": "renamed.txt"})

                self.assertEqual(response.status_code, 200)
                self.file.refresh_from_db()
                self.assertEqual(self.file.name, "renamed.txt")
                action, target = self.find_modal(RenameFolderFilesModal, self.folder.pk)
                self.assertIs(target, RenameFolderFilesModal)
                self.assertEqual(action.view.parent_instance, self.folder)

    def test_independent_child_modal_does_not_require_parent_permission(self):
        url = self.inline.get_action_url("RenameFileModal", object_id=self.file.pk)

        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"name": "independent.txt"})

        self.assertEqual(response.status_code, 200)
        self.file.refresh_from_db()
        self.assertEqual(self.file.name, "independent.txt")
        _, target = self.find_modal(RenameFileModal, self.file.pk)
        self.assertIs(target, RenameFileModal)

    def test_fieldset_modal_respects_parent_object_permission(self):
        self.grant_permissions(
            "view_file", "change_file", "view_folder", "change_folder"
        )
        self.folder.name = "Restricted"
        self.folder.save()

        self.assert_fieldset_modal_unavailable()

    def test_parent_access_does_not_replace_child_action_permission(self):
        self.grant_permissions("view_file", "view_folder", "change_folder")

        self.assert_fieldset_modal_unavailable()
