import re

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import path
from filer.admin import FolderAdmin
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdminThirdParty
from django_smartbase_admin.admin.site import SBAdminSite
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.const import AUTOCOMPLETE_SEARCH_NAME
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem

AUTOCOMPLETE_URL_RE = re.compile(r'"autocomplete_url": "(?P<url>[^"]+)"')


class ThirdPartyFolderAdmin(SBAdminThirdParty, FolderAdmin):
    change_form_template = "sb_admin/actions/change_form.html"


class ThirdPartyRoleConfiguration(SBAdminRoleConfiguration):
    pass


class ThirdPartyConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = ThirdPartyRoleConfiguration()
        folder_admin = test_admin_site._registry[Folder]
        folder_admin.init_view_static(configuration, Folder, test_admin_site)
        configuration.default_view = SBAdminMenuItem(view_id=folder_admin.get_id())
        return configuration


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(User, UserAdmin)
test_admin_site.register(Folder, ThirdPartyFolderAdmin)

urlpatterns = [
    path("sb-admin/", test_admin_site.urls),
    path("admin/", admin.site.urls),
]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=f"{__name__}.ThirdPartyConfiguration",
)
class ThirdPartyFormAutocompleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="folder-owner", email="owner@example.com", password="password"
        )
        cls.folder = Folder.objects.create(name="Products", owner=cls.user)

    def test_change_form_autocomplete_answers_in_a_new_request(self):
        self.client.force_login(self.user)
        change_page = self.client.get(
            f"/sb-admin/filer/folder/{self.folder.pk}/change/"
        )
        autocomplete_url = AUTOCOMPLETE_URL_RE.search(
            change_page.content.decode()
        ).group("url")

        response = self.client.post(
            autocomplete_url, {AUTOCOMPLETE_SEARCH_NAME: "folder"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("folder-owner", response.content.decode())
