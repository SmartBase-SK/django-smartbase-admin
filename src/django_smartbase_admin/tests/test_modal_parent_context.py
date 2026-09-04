from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.utils.html import escape

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import SBAdminSite
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_IS_MODAL_VAR,
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
    SBADMIN_PARENT_INSTANCE_MODEL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
    SBADMIN_RELOAD_ON_SAVE_VAR,
)
from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem


class ModalParentRoleConfiguration(SBAdminRoleConfiguration):
    pass


class ModalParentConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        configuration = ModalParentRoleConfiguration()
        group_admin = test_admin_site._registry[Group]
        group_admin.init_view_static(configuration, Group, test_admin_site)
        configuration.default_view = SBAdminMenuItem(view_id=group_admin.get_id())
        return configuration


class GroupAdmin(SBAdmin):
    sbadmin_fieldsets = ((None, {"fields": ("name",)}),)


test_admin_site = SBAdminSite(name="sb_admin")
test_admin_site.register(get_user_model(), UserAdmin)
test_admin_site.register(Group, GroupAdmin)

urlpatterns = [path("sb-admin/", test_admin_site.urls)]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION=(
        "django_smartbase_admin.tests.test_modal_parent_context."
        "ModalParentConfiguration"
    ),
)
class ModalParentContextPersistenceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="modal-parent-admin",
            email="modal-parent@example.com",
            password="password",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_invalid_modal_post_keeps_parent_context_in_next_post_url(self):
        add_url = reverse("sb_admin:auth_group_add")
        query = urlencode(
            {
                "_popup": "1",
                SBADMIN_IS_MODAL_VAR: "1",
                SBADMIN_RELOAD_ON_SAVE_VAR: "1",
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: (
                    "modal_app_attachment_id_parent"
                ),
                SBADMIN_PARENT_INSTANCE_MODEL_VAR: "app.parent",
                SBADMIN_PARENT_INSTANCE_PK_VAR: "42",
                SBADMIN_PARENT_INSTANCE_LABEL_VAR: "Parent #42",
            }
        )
        modal_url = f"{add_url}?{query}"
        expected_hx_post = f'hx-post="{add_url}?{escape(query)}"'

        initial_response = self.client.get(modal_url)
        self.assertEqual(initial_response.status_code, 200)
        self.assertContains(initial_response, expected_hx_post)

        invalid_response = self.client.post(modal_url, data={})
        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, expected_hx_post)
