from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.test import TestCase, override_settings
from django.urls import path, reverse
from filer.admin.imageadmin import ImageAdmin as FilerImageAdmin
from filer.models import Image

from django_smartbase_admin.admin.admin_base import SBAdminThirdParty
from django_smartbase_admin.admin.site import SBAdminSite
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem


class ImageChangeFormRoleConfiguration(SBAdminRoleConfiguration):
    pass


class ImageChangeFormConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = ImageChangeFormRoleConfiguration()
        image_admin = test_admin_site._registry[Image]
        image_admin.init_view_static(configuration, Image, test_admin_site)
        configuration.default_view = SBAdminMenuItem(view_id=image_admin.get_id())
        return configuration


class ImageChangeFormAdmin(SBAdminThirdParty, FilerImageAdmin):
    change_form_template = "sb_admin/integrations/filer/image_change_form.html"
    fieldsets = [(None, {"fields": ["default_alt_text", "default_caption"]})]


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(get_user_model(), UserAdmin)
test_admin_site.register(Image, ImageChangeFormAdmin)

urlpatterns = [
    path("sb-admin/", test_admin_site.urls),
    path("admin/", admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=(
        "django_smartbase_admin.tests.test_filer_image_change_form."
        "ImageChangeFormConfiguration"
    ),
    STATIC_URL="/static/",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class FilerImageChangeFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="image-admin",
            email="image-admin@example.com",
            password="password",
        )
        cls.image = Image.objects.create(
            name="Hero",
            original_filename="hero.jpg",
            owner=cls.user,
            default_alt_text="Old alt",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("sb_admin:filer_image_change", args=(self.image.pk,))

    def test_renders_preview_with_editable_fieldsets(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "filer-sb-image-preview")
        self.assertContains(response, 'name="default_alt_text"')
        self.assertContains(response, 'value="Old alt"')
        self.assertContains(response, 'name="default_caption"')
        self.assertContains(response, 'name="_save"')
        self.assertNotContains(response, 'name="_addanother"')

    def test_saves_edited_fields(self):
        response = self.client.post(
            self.url,
            {"default_alt_text": "New alt", "default_caption": "Caption"},
        )

        self.assertEqual(response.status_code, 302)
        self.image.refresh_from_db()
        self.assertEqual(self.image.default_alt_text, "New alt")
        self.assertEqual(self.image.default_caption, "Caption")
