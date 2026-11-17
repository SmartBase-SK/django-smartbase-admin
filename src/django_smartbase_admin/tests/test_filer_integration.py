from io import BytesIO
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import path, reverse
from filer.models import File, Folder, Image
from PIL import Image as PILImage

from django_smartbase_admin.admin.site import SBAdminSite
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.integration.filer import (
    SBAdminFilerFileAdmin,
    SBAdminFilerFolderAdmin,
    SBAdminFilerImageAdmin,
)


class FilerRoleConfiguration(SBAdminRoleConfiguration):
    pass


class FilerConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = FilerRoleConfiguration()
        for model in (Folder, File, Image):
            model_admin = test_admin_site._registry[model]
            model_admin.init_view_static(configuration, model, test_admin_site)
        configuration.default_view = SBAdminMenuItem(
            view_id=test_admin_site._registry[Image].get_id()
        )
        return configuration


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(get_user_model(), UserAdmin)
test_admin_site.register(Folder, SBAdminFilerFolderAdmin)
test_admin_site.register(File, SBAdminFilerFileAdmin)
test_admin_site.register(Image, SBAdminFilerImageAdmin)

urlpatterns = [
    path("sb-admin/", test_admin_site.urls),
    path("admin/", admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=(
        "django_smartbase_admin.tests.test_filer_integration.FilerConfiguration"
    ),
    STATIC_URL="/static/",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class FilerIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="filer-admin",
            email="filer-admin@example.com",
            password="password",
        )

    def setUp(self):
        self.client.force_login(self.user)
        content = BytesIO()
        PILImage.new("RGB", (3, 2)).save(content, format="PNG")
        self.image = Image.objects.create(
            name="Hero",
            original_filename="hero.png",
            file=SimpleUploadedFile("hero.png", content.getvalue()),
            default_alt_text="Old alt",
        )
        self.document = File.objects.create(
            name="Terms",
            original_filename="terms.txt",
            file=SimpleUploadedFile("terms.txt", b"terms"),
        )
        self.addCleanup(self.image.file.delete, save=False)
        self.addCleanup(self.document.file.delete, save=False)

    def image_change_url(self):
        return reverse("sb_admin:filer_image_change", args=(self.image.pk,))

    def test_image_change_view_uses_standard_detail_layout(self):
        response = self.client.get(self.image_change_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'<img src="{self.image.url}" alt="Old alt"')
        self.assertContains(response, 'name="default_alt_text"')
        self.assertNotContains(response, 'name="default_caption"')
        self.assertContains(response, "3×2 px")
        self.assertContains(response, f'href="{self.image.url}"')
        self.assertContains(response, "input-file-wrapper")
        self.assertNotContains(response, 'name="file-clear"')
        self.assertNotContains(response, 'name="_addanother"')
        self.assertNotContains(response, "field-display_canonical")

    def test_missing_image_redirects_instead_of_failing(self):
        response = self.client.get(
            reverse("sb_admin:filer_image_change", args=(self.image.pk + 1000,))
        )

        self.assertRedirects(
            response, reverse("sb_admin:index"), fetch_redirect_response=False
        )

    def test_canonical_url_shows_when_filer_urls_are_routed(self):
        with mock.patch(
            "django_smartbase_admin.integration.filer.filer_canonical_url_enabled",
            return_value=True,
        ):
            response = self.client.get(self.image_change_url())

        self.assertContains(response, "field-display_canonical")

    def test_image_save_returns_to_sb_admin_folder_listing(self):
        response = self.client.post(
            self.image_change_url(),
            {"name": "Hero", "default_alt_text": "New alt", "_save": "Save"},
        )

        self.assertRedirects(
            response,
            reverse("sb_admin:filer-directory_listing-unfiled_images"),
            fetch_redirect_response=False,
        )
        self.image.refresh_from_db()
        self.assertEqual(self.image.default_alt_text, "New alt")

    def test_file_save_returns_to_sb_admin_folder_listing(self):
        response = self.client.post(
            reverse("sb_admin:filer_file_change", args=(self.document.pk,)),
            {"name": "Conditions", "owner": "", "description": "", "_save": "Save"},
        )

        self.assertRedirects(
            response,
            reverse("sb_admin:filer-directory_listing-unfiled_images"),
            fetch_redirect_response=False,
        )
        self.document.refresh_from_db()
        self.assertEqual(self.document.name, "Conditions")


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
)
class FilerImageMCPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        SBAdminThreadLocalService.clear_request()
        cls.user = get_user_model().objects.create_superuser(
            username="mcp-filer", email="mcp-filer@example.com", password="password"
        )

    def setUp(self):
        SBAdminThreadLocalService.clear_request()
        self.with_alt = self.create_image("with-alt.png", default_alt_text="Described")
        self.without_alt = self.create_image("without-alt.png")
        MCPToolTestConfig().init_view_map()
        MCPToolTestConfig.view_permission_for = None
        self.tools = SBAdminTools(request=build_mcp_request(self.user))

    def create_image(self, filename, **fields):
        content = BytesIO()
        PILImage.new("RGB", (3, 2)).save(content, format="PNG")
        image = Image.objects.create(
            original_filename=filename,
            file=SimpleUploadedFile(filename, content.getvalue()),
            **fields,
        )
        self.addCleanup(image.file.delete, save=False)
        return image

    def test_lists_images_without_alt_text(self):
        result = self.tools.list_rows(
            "filer_image",
            fields=["original_filename", "default_alt_text"],
            filter_data={"has_alt_text": False},
        )

        self.assertEqual(
            [row["original_filename"] for row in result["data"]], ["without-alt.png"]
        )

    def test_update_detail_sets_alt_text(self):
        result = self.tools.update_detail(
            "filer_image",
            str(self.without_alt.pk),
            component_values={"main": {"default_alt_text": "Now described"}},
        )

        self.assertEqual(result["status"], "ok")
        self.without_alt.refresh_from_db()
        self.assertEqual(self.without_alt.default_alt_text, "Now described")
