from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminInline
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
    SBADMIN_PARENT_INSTANCE_MODEL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
)


class _ChildAdmin(SBAdmin):
    sbadmin_is_generic_model = True


class GenericRelationParentValidationTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.ct = ContentType.objects.get_for_model(Folder)
        self.visible = Folder.objects.create(name="visible")
        self.hidden = Folder.objects.create(name="hidden")

    def _request(self, pk):
        return self.factory.post(
            "/",
            data={
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: "modal_inline",
                SBADMIN_PARENT_INSTANCE_MODEL_VAR: (
                    f"{self.ct.app_label}.{self.ct.model}"
                ),
                SBADMIN_PARENT_INSTANCE_PK_VAR: str(pk),
            },
        )

    def test_forged_parent_pk_outside_restricted_queryset_is_denied(self):
        parent_admin = MagicMock()
        parent_admin.has_view_permission.return_value = True
        parent_admin.get_queryset.return_value = Folder.objects.filter(
            pk=self.visible.pk
        )

        with patch.dict(
            "django_smartbase_admin.admin.site.sb_admin_site._registry",
            {Folder: parent_admin},
        ):
            with self.assertRaises(PermissionDenied):
                _ChildAdmin.set_generic_relation_from_parent(
                    self._request(self.hidden.pk), SimpleNamespace()
                )

            obj = SimpleNamespace()
            _ChildAdmin.set_generic_relation_from_parent(
                self._request(self.visible.pk), obj
            )
            self.assertEqual(obj.object_id, self.visible.pk)

    def test_generated_inline_parent_token_round_trips_through_parser(self):
        inline = SBAdminInline.__new__(SBAdminInline)
        inline.model = Group
        inline.parent_model = Folder
        inline.parent_instance = self.visible
        inline.sortable_field_name = None
        inline.sb_admin_add_modal = False
        with patch.object(
            inline, "get_sbadmin_inline_list_actions_processed", return_value=[]
        ):
            parent_data = inline.get_context_data(self.factory.get("/"))["parent_data"]

        request = self.factory.post(
            "/",
            data={
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: (
                    f"modal_{parent_data[SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR]}"
                ),
                SBADMIN_PARENT_INSTANCE_MODEL_VAR: parent_data[
                    SBADMIN_PARENT_INSTANCE_MODEL_VAR
                ],
                SBADMIN_PARENT_INSTANCE_PK_VAR: str(self.visible.pk),
            },
        )
        parent_admin = MagicMock()
        parent_admin.has_view_permission.return_value = True
        parent_admin.get_queryset.return_value = Folder.objects.all()
        obj = SimpleNamespace()

        with patch.dict(
            "django_smartbase_admin.admin.site.sb_admin_site._registry",
            {Folder: parent_admin},
        ):
            _ChildAdmin.set_generic_relation_from_parent(request, obj)

        self.assertEqual(obj.content_type, self.ct)
        self.assertEqual(obj.object_id, self.visible.pk)

    def test_parent_model_metadata_does_not_change_widget_target(self):
        input_id = "modal_auth_group_id_folder"
        request = self.factory.get(
            "/",
            data={
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: input_id,
                SBADMIN_PARENT_INSTANCE_MODEL_VAR: "filer.folder",
                SBADMIN_PARENT_INSTANCE_PK_VAR: str(self.visible.pk),
            },
        )
        widget = SimpleNamespace(input_id=input_id)

        is_parent_widget = SBAdminAutocompleteWidget._should_preselect_parent_instance(
            widget, request
        )

        self.assertIs(is_parent_widget, True)
