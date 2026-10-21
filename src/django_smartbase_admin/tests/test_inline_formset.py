import re

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from django_smartbase_admin.admin.admin_base import (
    SBAdminGenericInlineFormSet,
    SBAdminNestedInlineFormSet,
)
from django_smartbase_admin.engine.fake_inline import SBAdminFakeInlineFormset
from django_smartbase_admin.engine.inline_formset import LoadedRowsPkFormsetMixin

_PERMISSION_BY_PK = re.compile(
    r'FROM "auth_permission" WHERE "auth_permission"."id" = '
)


class _PermissionFormset(LoadedRowsPkFormsetMixin, BaseInlineFormSet):
    pass


PermissionFormset = inlineformset_factory(
    ContentType,
    Permission,
    formset=_PermissionFormset,
    fields=["name", "codename"],
    extra=0,
)


class LoadedRowsPkFormsetMixinTests(TestCase):
    def setUp(self):
        self.content_type = ContentType.objects.create(
            app_label="sb_test", model="loadedrows"
        )
        self.permissions = [
            Permission.objects.create(
                content_type=self.content_type, codename=f"row_{i}", name=f"Row {i}"
            )
            for i in range(3)
        ]

    def _data(self, pks):
        prefix = PermissionFormset.get_default_prefix()
        data = {
            f"{prefix}-TOTAL_FORMS": str(len(pks)),
            f"{prefix}-INITIAL_FORMS": str(len(pks)),
        }
        for index, pk in enumerate(pks):
            data[f"{prefix}-{index}-id"] = str(pk)
            data[f"{prefix}-{index}-name"] = f"Renamed {index}"
            data[f"{prefix}-{index}-codename"] = f"row_{index}"
        return data

    def test_existing_rows_resolve_without_a_query_per_row(self):
        formset = PermissionFormset(
            self._data([permission.pk for permission in self.permissions]),
            instance=self.content_type,
        )

        with CaptureQueriesContext(connection) as captured:
            self.assertTrue(formset.is_valid(), formset.errors)

        self.assertEqual(
            [
                q
                for q in captured.captured_queries
                if _PERMISSION_BY_PK.search(q["sql"])
            ],
            [],
        )
        self.assertEqual(
            [form.cleaned_data["id"] for form in formset.forms], self.permissions
        )

    def test_unknown_pk_is_still_rejected(self):
        formset = PermissionFormset(
            self._data([self.permissions[0].pk, 0]), instance=self.content_type
        )

        self.assertFalse(formset.is_valid())
        self.assertIn("id", formset.forms[1].errors)

    def test_sbadmin_inline_formsets_resolve_loaded_rows(self):
        for formset_class in (
            SBAdminNestedInlineFormSet,
            SBAdminGenericInlineFormSet,
            SBAdminFakeInlineFormset,
        ):
            with self.subTest(formset_class=formset_class.__name__):
                self.assertTrue(issubclass(formset_class, LoadedRowsPkFormsetMixin))
