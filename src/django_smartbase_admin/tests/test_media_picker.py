from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone
from django.utils.formats import date_format
from filer import settings as filer_settings
from filer.admin import ClipboardAdmin, FileAdmin, FolderAdmin
from filer.admin.imageadmin import ImageAdmin as FilerImageAdmin
from filer.fields.file import FilerFileField
from filer.fields.image import FilerImageField
from filer.cache import clear_folder_permission_cache
from filer.models import Clipboard, File, Folder, FolderPermission, Image

from django_smartbase_admin.admin.admin_base import SBAdminFormFieldWidgetsMixin
from django_smartbase_admin.admin.site import SBAdminSite, sb_admin_site
from django_smartbase_admin.admin.widgets import (
    SBAdminFilerImagePickerWidget,
    SBAdminFilerPickerWidget,
)
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem


class MediaPickerRoleConfiguration(SBAdminRoleConfiguration):
    denied_permissions = set()
    restrict_qs = None

    def has_permission(
        self,
        request,
        request_data,
        view,
        model=None,
        obj=None,
        permission=None,
    ):
        return (model, permission) not in type(self).denied_permissions

    def restrict_queryset(
        self,
        qs,
        model,
        request,
        request_data,
        global_filter=True,
        global_filter_data_map=None,
    ):
        restrict_qs = type(self).restrict_qs
        return qs if restrict_qs is None else restrict_qs(qs, model)


class MediaPickerConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = MediaPickerRoleConfiguration()
        if configuration.default_view is None and configuration.view_map:
            configuration.default_view = SBAdminMenuItem(
                view_id=next(iter(configuration.view_map))
            )
        return configuration


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(get_user_model(), UserAdmin)
test_admin_site.register(Folder, FolderAdmin)
test_admin_site.register(File, FileAdmin)
test_admin_site.register(Image, FilerImageAdmin)
test_admin_site.register(Clipboard, ClipboardAdmin)

urlpatterns = [
    path("sb-admin/", test_admin_site.urls),
    path("admin/", admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=(
        "django_smartbase_admin.tests.test_media_picker.MediaPickerConfiguration"
    ),
)
class MediaPickerViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="picker-admin",
            email="picker@example.com",
            password="password",
        )
        cls.folder = Folder.objects.create(name="Products", owner=cls.user)
        cls.child = Folder.objects.create(
            name="Summer",
            owner=cls.user,
            parent=cls.folder,
        )
        cls.apple = Image.objects.create(
            name="Apple",
            original_filename="apple.jpg",
            folder=cls.folder,
            owner=cls.user,
            is_public=True,
        )
        cls.banana = Image.objects.create(
            name="",
            original_filename="banana.jpg",
            folder=cls.child,
            owner=cls.user,
            is_public=True,
        )
        cls.private = Image.objects.create(
            name="Private",
            original_filename="private.jpg",
            folder=cls.folder,
            owner=cls.user,
            is_public=False,
        )
        cls.document = File.objects.create(
            name="Manual",
            original_filename="manual.pdf",
            folder=cls.folder,
            owner=cls.user,
            is_public=True,
        )
        File.objects.filter(pk=cls.apple.pk).update(
            uploaded_at=timezone.now() - timedelta(days=1)
        )

    def setUp(self):
        MediaPickerRoleConfiguration.denied_permissions = set()
        MediaPickerRoleConfiguration.restrict_qs = None
        self.client.force_login(self.user)

    def tearDown(self):
        MediaPickerRoleConfiguration.denied_permissions = set()
        MediaPickerRoleConfiguration.restrict_qs = None

    @staticmethod
    def grant_filer_permission(user, codename):
        permission = Permission.objects.get(
            content_type__app_label="filer",
            codename=codename,
        )
        user.user_permissions.add(permission)

    def get_picker(self, **params):
        return self.client.get(reverse("sb_admin:media_picker"), params)

    def test_lists_direct_folders_and_images(self):
        response = self.get_picker(folder=self.folder.pk)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "sb_admin/media_picker/picker.html")
        data = response.context
        self.assertEqual(
            data["folder"],
            {
                "id": self.folder.pk,
                "name": "Products",
                "change_url": reverse(
                    "sb_admin:filer_folder_change", args=[self.folder.pk]
                ),
            },
        )
        self.assertEqual(
            data["folders"],
            [
                {
                    "id": self.child.pk,
                    "name": "Summer",
                    "change_url": reverse(
                        "sb_admin:filer_folder_change", args=[self.child.pk]
                    ),
                }
            ],
        )
        self.assertEqual(
            [item["name"] for item in data["items"]],
            ["Private", "Apple"],
        )
        self.assertContains(response, 'loading="lazy"', count=2)
        self.assertTrue(data["permissions"]["can_upload"])
        self.assertIn(str(self.folder.pk), data["upload"]["url"])

    def test_uploads_to_root_with_existing_filer_endpoint(self):
        self.get_picker(folder=self.folder.pk)
        response = self.get_picker()

        self.assertTrue(response.context["permissions"]["can_upload"])
        upload_url = response.context["upload"]["url"]
        self.assertIn("/operations/upload/no_folder/", upload_url)
        self.assertIsNone(self.client.session["filer_last_folder_id"])

        image = SimpleUploadedFile(
            "root.gif",
            (
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
                b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00"
                b"\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )
        upload_response = self.client.post(upload_url, {"file": image})

        self.assertEqual(upload_response.status_code, 200)
        uploaded = Image.objects.get(original_filename="root.gif")
        self.assertIsNone(uploaded.folder)
        uploaded.delete()

    def test_search_is_global_and_matches_display_filename(self):
        response = self.get_picker(folder=self.folder.pk, q="banana")

        data = response.context
        self.assertEqual(data["folders"], [])
        self.assertEqual([item["id"] for item in data["items"]], [self.banana.pk])

    def test_search_is_global_and_matches_folder_name(self):
        response = self.get_picker(folder=self.folder.pk, q="summer")

        data = response.context
        self.assertEqual(data["folders"][0]["id"], self.child.pk)

    def test_edit_links_open_folder_image_and_file_change_pages(self):
        image_response = self.get_picker(folder=self.folder.pk, picker_type="image")
        file_response = self.get_picker(folder=self.folder.pk, picker_type="file")

        folder_url = reverse("sb_admin:filer_folder_change", args=[self.child.pk])
        image_url = reverse("sb_admin:filer_image_change", args=[self.apple.pk])
        file_url = reverse("sb_admin:filer_file_change", args=[self.document.pk])

        self.assertContains(
            image_response,
            f'href="{folder_url}" target="_blank" rel="noopener noreferrer"',
        )
        self.assertContains(
            image_response,
            f'href="{image_url}" target="_blank" rel="noopener noreferrer"',
        )
        self.assertContains(
            file_response,
            f'href="{file_url}" target="_blank" rel="noopener noreferrer"',
        )
        self.assertContains(image_response, 'class="sb-media-picker__edit"')
        self.assertContains(image_response, 'xlink:href="#Edit"')

    def test_file_picker_lists_all_filer_file_types(self):
        response = self.get_picker(folder=self.folder.pk, picker_type="file")

        self.assertEqual(response.context["picker_type"], "file")
        self.assertEqual(
            {item["id"] for item in response.context["items"]},
            {self.apple.pk, self.private.pk, self.document.pk},
        )
        document = next(
            item for item in response.context["items"] if item["id"] == self.document.pk
        )
        self.assertEqual(document["reference"], f"filer://file/{self.document.pk}")
        self.assertContains(response, "Select file")
        self.assertContains(response, "Search files")
        self.assertContains(response, 'data-picker-type="file"')
        self.assertNotContains(response, 'accept="image/*"')
        self.assertIn("picker_type=file", response.context["root_url"])
        self.assertIn("picker_type=file", response.context["folder_entries"][0]["url"])

    def test_image_picker_excludes_non_image_files(self):
        response = self.get_picker(folder=self.folder.pk, picker_type="image")

        self.assertNotIn(
            self.document.pk,
            {item["id"] for item in response.context["items"]},
        )
        self.assertContains(response, 'accept="image/*"')

    def test_name_and_date_ordering(self):
        newest = self.get_picker(q="a", order_by="-uploaded_at").context["items"]
        alphabetical = self.get_picker(q="a", order_by="name").context["items"]

        self.assertEqual(
            [item["id"] for item in newest],
            [self.private.pk, self.banana.pk, self.apple.pk],
        )
        self.assertEqual(
            [item["id"] for item in alphabetical],
            [self.apple.pk, self.banana.pk, self.private.pk],
        )

    def test_item_upload_date_is_rendered_from_datetime(self):
        response = self.get_picker(folder=self.folder.pk)
        apple = next(
            item for item in response.context["items"] if item["id"] == self.apple.pk
        )

        self.assertIsInstance(apple["uploaded_at"], datetime)
        self.assertContains(
            response,
            date_format(apple["uploaded_at"], "SHORT_DATE_FORMAT"),
        )
        self.assertContains(
            response,
            f'data-uploaded-at="{timezone.localtime(apple["uploaded_at"]).isoformat()}"',
        )

    def test_folders_follow_selected_sort_but_stay_before_files(self):
        alpha = Folder.objects.create(
            name="Alpha",
            owner=self.user,
            parent=self.folder,
        )
        zebra = Folder.objects.create(
            name="Zebra",
            owner=self.user,
            parent=self.folder,
        )
        now = timezone.now()
        Folder.objects.filter(pk=alpha.pk).update(uploaded_at=now - timedelta(days=2))
        Folder.objects.filter(pk=self.child.pk).update(
            uploaded_at=now - timedelta(days=1)
        )
        Folder.objects.filter(pk=zebra.pk).update(uploaded_at=now)

        oldest = self.get_picker(
            folder=self.folder.pk,
            order_by="uploaded_at",
        ).context
        newest = self.get_picker(
            folder=self.folder.pk,
            order_by="-uploaded_at",
        ).context
        alphabetical = self.get_picker(
            folder=self.folder.pk,
            order_by="name",
        ).context
        reverse_alphabetical = self.get_picker(
            folder=self.folder.pk,
            order_by="-name",
        ).context

        self.assertEqual(
            [folder["name"] for folder in oldest["folders"]],
            ["Alpha", "Summer", "Zebra"],
        )
        self.assertEqual(
            [folder["name"] for folder in newest["folders"]],
            ["Zebra", "Summer", "Alpha"],
        )
        self.assertEqual(
            [folder["name"] for folder in alphabetical["folders"]],
            ["Alpha", "Summer", "Zebra"],
        )
        self.assertEqual(
            [folder["name"] for folder in reverse_alphabetical["folders"]],
            ["Zebra", "Summer", "Alpha"],
        )
        self.assertTrue(oldest["items"])

    def test_paginates_images_by_one_hundred(self):
        for index in range(101):
            Image.objects.create(
                name=f"Pagination {index:02d}",
                original_filename=f"pagination-{index:02d}.jpg",
                owner=self.user,
                is_public=True,
            )

        first_response = self.get_picker(q="Pagination", order_by="name")
        first_page = first_response.context
        second_page = self.get_picker(
            q="Pagination",
            order_by="name",
            page=2,
        ).context

        self.assertEqual(len(first_page["items"]), 100)
        self.assertEqual(first_page["pagination"].paginator.num_pages, 2)
        self.assertTrue(first_page["pagination"].has_next())
        self.assertEqual(first_page["pagination"].start_index(), 1)
        self.assertEqual(first_page["pagination"].end_index(), 100)
        self.assertContains(first_response, "sb-media-picker__paginator")
        self.assertContains(first_response, "sb-media-picker__page is-active")
        self.assertContains(first_response, 'xlink:href="#Left"')
        self.assertContains(first_response, 'xlink:href="#Right"')
        self.assertEqual(len(second_page["items"]), 1)
        self.assertTrue(second_page["pagination"].has_previous())

    def test_paginates_folders_and_images_as_one_result_set(self):
        for index in range(99):
            Image.objects.create(
                name=f"Product {index:02d}",
                original_filename=f"product-{index:02d}.jpg",
                folder=self.folder,
                owner=self.user,
                is_public=True,
            )

        first_page = self.get_picker(folder=self.folder.pk).context
        second_page = self.get_picker(folder=self.folder.pk, page=2).context

        self.assertEqual(
            [folder["id"] for folder in first_page["folders"]], [self.child.pk]
        )
        self.assertEqual(len(first_page["items"]), 99)
        self.assertEqual(first_page["pagination"].paginator.count, 102)
        self.assertEqual(second_page["folders"], [])
        self.assertEqual(len(second_page["items"]), 2)

    def test_creates_folder_in_current_folder(self):
        response = self.client.post(
            reverse("sb_admin:media_picker"),
            data={"folder": self.folder.pk, "name": "Campaigns"},
        )

        self.assertEqual(response.status_code, 200)
        created = Folder.objects.get(name="Campaigns")
        self.assertEqual(created.parent, self.folder)
        self.assertEqual(created.owner, self.user)

    def test_rejects_duplicate_folder_name(self):
        response = self.client.post(
            reverse("sb_admin:media_picker"),
            data={"folder": self.folder.pk, "name": "Summer"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_fragment_uses_htmx_for_server_rendered_interactions(self):
        response = self.get_picker(folder=self.folder.pk)

        self.assertContains(response, 'hx-trigger="input changed delay:300ms, search"')
        self.assertContains(response, "hx-preserve")
        self.assertContains(
            response,
            'hx-sync="closest [data-picker-surface]:replace"',
        )
        self.assertContains(response, "data-picker-clear-search")
        self.assertContains(response, 'hx-swap="outerHTML"')
        self.assertContains(response, 'hx-indicator="#sb-media-picker-loading"')
        self.assertContains(response, "data-picker-loading-text")
        self.assertContains(response, 'data-uploading-label="Uploading"')
        self.assertContains(response, "data-picker-drop-overlay")
        self.assertContains(response, "data-picker-new-folder")
        self.assertContains(response, "data-picker-new-folder-trigger")
        self.assertContains(response, "data-picker-upload-trigger")
        self.assertContains(response, "data-picker-item")
        self.assertContains(response, 'title="Summer"')
        self.assertContains(response, 'title="Apple"')
        self.assertContains(response, "sb-media-picker__breadcrumb-separator")
        self.assertContains(response, 'xlink:href="#Right-small"')
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, 'xlink:href="#Check-small"')
        self.assertNotContains(response, "&#10003;")
        self.assertNotContains(response, 'class="btn')
        self.assertNotContains(response, 'class="input')
        self.assertNotContains(response, "tabulator-")
        self.assertNotContains(response, "htmx-indicator")

    def test_requires_staff_and_filer_directory_access(self):
        staff = get_user_model().objects.create_user(
            username="staff",
            password="password",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.get_picker()

        self.assertEqual(response.status_code, 403)

    def test_requires_sbadmin_view_permission_for_picker_model(self):
        MediaPickerRoleConfiguration.denied_permissions = {(Image, "view")}

        response = self.get_picker(folder=self.folder.pk)

        self.assertEqual(response.status_code, 403)

    def test_applies_sbadmin_restrictions_to_folders_and_items(self):
        def restrict_queryset(queryset, model):
            if model is Folder:
                return queryset.exclude(pk=self.child.pk)
            if model is Image:
                return queryset.exclude(pk=self.private.pk)
            return queryset

        MediaPickerRoleConfiguration.restrict_qs = restrict_queryset

        response = self.get_picker(folder=self.folder.pk)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            self.child.pk,
            {folder["id"] for folder in response.context["folders"]},
        )
        self.assertNotIn(
            self.private.pk,
            {item["id"] for item in response.context["items"]},
        )

    def test_restricted_current_folder_returns_not_found(self):
        MediaPickerRoleConfiguration.restrict_qs = lambda queryset, model: (
            queryset.exclude(pk=self.child.pk) if model is Folder else queryset
        )

        response = self.get_picker(folder=self.child.pk)

        self.assertEqual(response.status_code, 404)

    def test_create_folder_requires_sbadmin_add_permission(self):
        MediaPickerRoleConfiguration.denied_permissions = {(Folder, "add")}

        response = self.client.post(
            reverse("sb_admin:media_picker"),
            data={"folder": self.folder.pk, "name": "Denied"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Folder.objects.filter(name="Denied").exists())

    def test_create_folder_rejects_restricted_parent(self):
        MediaPickerRoleConfiguration.restrict_qs = lambda queryset, model: (
            queryset.exclude(pk=self.folder.pk) if model is Folder else queryset
        )

        response = self.client.post(
            reverse("sb_admin:media_picker"),
            data={"folder": self.folder.pk, "name": "Denied parent"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Folder.objects.filter(name="Denied parent").exists())

    def test_root_only_lists_unfiled_items_owned_by_regular_user(self):
        staff = get_user_model().objects.create_user(
            username="root-picker-staff",
            password="password",
            is_staff=True,
        )
        self.grant_filer_permission(staff, "can_use_directory_listing")
        own = Image.objects.create(
            name="Own root image",
            original_filename="own-root.jpg",
            owner=staff,
            is_public=True,
        )
        foreign = Image.objects.create(
            name="Foreign root image",
            original_filename="foreign-root.jpg",
            owner=self.user,
            is_public=True,
        )
        self.client.force_login(staff)

        clear_folder_permission_cache(staff)
        with mock.patch.object(filer_settings, "FILER_ENABLE_PERMISSIONS", True):
            response = self.get_picker()

        item_ids = {item["id"] for item in response.context["items"]}
        self.assertIn(own.pk, item_ids)
        self.assertNotIn(foreign.pk, item_ids)

    def test_breadcrumbs_do_not_expose_unreadable_ancestors(self):
        staff = get_user_model().objects.create_user(
            username="breadcrumb-picker-staff",
            password="password",
            is_staff=True,
        )
        self.grant_filer_permission(staff, "can_use_directory_listing")
        FolderPermission.objects.create(
            folder=self.child,
            type=FolderPermission.THIS,
            user=staff,
            can_read=FolderPermission.ALLOW,
        )
        clear_folder_permission_cache(staff)
        self.client.force_login(staff)

        with mock.patch.object(filer_settings, "FILER_ENABLE_PERMISSIONS", True):
            response = self.get_picker(folder=self.child.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [folder["id"] for folder in response.context["breadcrumbs"]],
            [self.child.pk],
        )

    def test_filer_image_field_uses_reusable_picker_widget(self):
        self.assertIs(
            SBAdminFormFieldWidgetsMixin.db_field_widgets[FilerImageField],
            SBAdminFilerImagePickerWidget,
        )

    def test_filer_file_field_uses_reusable_picker_widget(self):
        self.assertIs(
            SBAdminFormFieldWidgetsMixin.db_field_widgets[FilerFileField],
            SBAdminFilerPickerWidget,
        )

    def test_widget_renders_selected_image_and_media(self):
        model_field = FilerImageField(on_delete=models.SET_NULL, null=True)
        model_field.remote_field.model = Image
        model_field.remote_field.field_name = Image._meta.pk.name
        form_field = model_field.formfield()
        form_field.view = SimpleNamespace(admin_site=sb_admin_site)
        widget = SBAdminFilerImagePickerWidget(form_field=form_field)

        html = widget.render(
            "hero_image",
            self.apple.pk,
            attrs={"id": "id_hero_image"},
        )

        self.assertIn("data-sb-media-picker-widget", html)
        self.assertIn(reverse("sb_admin:media_picker"), html)
        self.assertIn(f'value="{self.apple.pk}"', html)
        self.assertIn("Apple", html)
        self.assertIn("js-filer-dropzone", html)
        self.assertIn("data-picker-widget-dropzone", html)
        self.assertIn("data-picker-empty-prompt", html)
        self.assertIn("sb-media-picker-widget__content", html)
        self.assertIn("/operations/upload/no_folder/", html)
        self.assertIn("data-sb-media-picker-trigger", html)
        self.assertIn("sb_admin/dist/media_picker.js", str(widget.media))
        self.assertIn("sb_admin/dist/media_picker_style.css", str(widget.media))
        self.assertIn("filer/js/dist/admin-file-widget.bundle.js", str(widget.media))
        self.assertNotIn("filer/css/admin_filer.css", str(widget.media))
        self.assertNotIn("filer/css/admin_filer.fa.icons.css", str(widget.media))

    def test_widget_hides_metadata_for_restricted_selected_item(self):
        MediaPickerRoleConfiguration.restrict_qs = lambda queryset, model: (
            queryset.exclude(pk=self.private.pk) if model is Image else queryset
        )
        request = self.get_picker(folder=self.folder.pk).wsgi_request
        model_field = FilerImageField(on_delete=models.SET_NULL, null=True)
        model_field.remote_field.model = Image
        model_field.remote_field.field_name = Image._meta.pk.name
        form_field = model_field.formfield()
        view = SimpleNamespace(admin_site=sb_admin_site)
        form_field.view = view
        widget = SBAdminFilerImagePickerWidget(form_field=form_field)
        widget.init_widget_dynamic(
            SimpleNamespace(initial={"hero_image": self.private.pk}),
            form_field,
            "hero_image",
            view,
            request,
        )

        html = widget.render("hero_image", self.private.pk)

        self.assertIn(f'value="{self.private.pk}"', html)
        self.assertNotIn("Private", html)

    def test_widget_rejects_changed_restricted_item_id(self):
        MediaPickerRoleConfiguration.restrict_qs = lambda queryset, model: (
            queryset.exclude(pk=self.private.pk) if model is Image else queryset
        )
        request = self.get_picker(folder=self.folder.pk).wsgi_request
        model_field = FilerImageField(on_delete=models.SET_NULL, null=True)
        model_field.remote_field.model = Image
        model_field.remote_field.field_name = Image._meta.pk.name
        form_field = model_field.formfield()
        view = SimpleNamespace(admin_site=sb_admin_site)
        form_field.view = view
        widget = SBAdminFilerImagePickerWidget(form_field=form_field)
        widget.init_widget_dynamic(
            SimpleNamespace(initial={"hero_image": self.apple.pk}),
            form_field,
            "hero_image",
            view,
            request,
        )

        value = widget.value_from_datadict(
            {"hero_image": str(self.private.pk)},
            {},
            "hero_image",
        )

        with self.assertRaises(ValidationError):
            form_field.clean(value)

    def test_file_widget_renders_selected_file_and_media(self):
        model_field = FilerFileField(on_delete=models.SET_NULL, null=True)
        model_field.remote_field.model = File
        model_field.remote_field.field_name = File._meta.pk.name
        form_field = model_field.formfield()
        form_field.view = SimpleNamespace(admin_site=sb_admin_site)
        widget = SBAdminFilerPickerWidget(form_field=form_field)

        html = widget.render(
            "manual",
            self.document.pk,
            attrs={"id": "id_manual"},
        )

        self.assertIn('data-picker-type="file"', html)
        self.assertIn("picker_type=file", html)
        self.assertIn(f'value="{self.document.pk}"', html)
        self.assertIn("Manual", html)
        self.assertIn("Change file", html)
