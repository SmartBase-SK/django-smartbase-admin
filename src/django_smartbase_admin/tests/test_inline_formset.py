import re

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from django_smartbase_admin.admin.admin_base import SBAdminNestedInlineFormSet
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


NestedPermissionFormset = inlineformset_factory(
    ContentType,
    Permission,
    formset=SBAdminNestedInlineFormSet,
    fields=["name", "codename"],
    extra=0,
)


class SBAdminNestedInlineFormSetSaveTests(TestCase):
    def setUp(self):
        self.content_type = ContentType.objects.create(
            app_label="sb_test", model="nestedsave"
        )
        self.other_content_type = ContentType.objects.create(
            app_label="sb_test", model="nestedsaveother"
        )
        self.permissions = [
            Permission.objects.create(
                content_type=self.content_type, codename=f"row_{i}", name=f"Row {i}"
            )
            for i in range(3)
        ]
        self.foreign = Permission.objects.create(
            content_type=self.other_content_type, codename="foreign", name="Foreign"
        )

    def _data(self, rows):
        prefix = NestedPermissionFormset.get_default_prefix()
        data = {
            f"{prefix}-TOTAL_FORMS": str(len(rows)),
            f"{prefix}-INITIAL_FORMS": str(len(rows)),
        }
        for index, (permission, name, delete) in enumerate(rows):
            data[f"{prefix}-{index}-id"] = str(permission.pk)
            data[f"{prefix}-{index}-name"] = name
            data[f"{prefix}-{index}-codename"] = permission.codename
            if delete:
                data[f"{prefix}-{index}-DELETE"] = "on"
        return data

    def _formset(self, rows, *, is_nested=False):
        formset = NestedPermissionFormset(self._data(rows), instance=self.content_type)
        formset.is_nested = is_nested
        self.assertTrue(formset.is_valid(), formset.errors)
        return formset

    def test_validation_reads_no_row_by_pk(self):
        formset = NestedPermissionFormset(
            self._data(
                [
                    (permission, permission.name, False)
                    for permission in self.permissions
                ]
            ),
            instance=self.content_type,
        )

        with CaptureQueriesContext(connection) as captured:
            self.assertTrue(formset.is_valid(), formset.errors)

        self.assertEqual(
            [
                q["sql"]
                for q in captured.captured_queries
                if _PERMISSION_BY_PK.search(q["sql"])
            ],
            [],
        )

    def test_top_level_save_reads_no_row_again(self):
        unchanged, renamed, deleted = self.permissions
        formset = self._formset(
            [
                (unchanged, unchanged.name, False),
                (renamed, "Renamed", False),
                (deleted, deleted.name, True),
            ]
        )

        with CaptureQueriesContext(connection) as captured:
            formset.save()

        self.assertEqual(
            [
                q["sql"]
                for q in captured.captured_queries
                if q["sql"].startswith("SELECT") and _PERMISSION_BY_PK.search(q["sql"])
            ],
            [],
        )
        self.assertEqual(formset.changed_objects, [(renamed, ["name"])])
        self.assertEqual([obj.name for obj in formset.deleted_objects], [deleted.name])
        renamed.refresh_from_db()
        self.assertEqual(renamed.name, "Renamed")
        self.assertFalse(Permission.objects.filter(pk=deleted.pk).exists())

    def test_top_level_ignores_a_posted_row_of_another_parent(self):
        formset = self._formset([(self.foreign, "Taken over", False)])

        formset.save()

        self.foreign.refresh_from_db()
        self.assertEqual(
            (self.foreign.content_type, self.foreign.name),
            (self.other_content_type, "Foreign"),
        )

    def test_nested_formset_still_moves_a_row_dragged_in_from_another_parent(self):
        formset = self._formset([(self.foreign, "Foreign", False)], is_nested=True)

        formset.save()

        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.content_type, self.content_type)

    def test_add_view_ignores_a_posted_row_of_another_parent(self):
        # The admin add flow: inlines are validated against the unsaved parent,
        # which is saved before them.
        parent = ContentType(app_label="sb_test", model="unsaved")
        formset = NestedPermissionFormset(
            self._data([(self.foreign, "Taken over", False)]), instance=parent
        )
        self.assertTrue(formset.is_valid(), formset.errors)
        parent.save()

        formset.save()

        self.foreign.refresh_from_db()
        self.assertEqual(
            (self.foreign.content_type, self.foreign.name),
            (self.other_content_type, "Foreign"),
        )
