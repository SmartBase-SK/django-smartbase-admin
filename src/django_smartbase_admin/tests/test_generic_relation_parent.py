from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from filer.models import Folder

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
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
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: f"modal_inline_{self.ct.app_label}_{self.ct.model}",
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
