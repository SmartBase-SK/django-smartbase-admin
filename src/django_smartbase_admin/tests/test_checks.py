"""Tests for the SBAdmin system checks (sbadmin.W001..W003).

Each per-admin helper is invoked directly with fabricated admin classes so we
don't depend on the global ``sb_admin_site`` registry or full Django admin
plumbing.
"""

from __future__ import annotations

from unittest import TestCase

from django_smartbase_admin.checks import (
    check_duplicate_filter_field_for_admin,
    check_ordering_columns_for_admin,
    check_view_config_filter_keys_for_admin,
)
from django_smartbase_admin.engine.field import SBAdminField


class _SentinelFilterWidget:
    """Stand-in that satisfies ``_has_filter`` without dragging in the widget stack."""


class _FakeAdmin:
    def __init__(
        self,
        *,
        sbadmin_list_display=(),
        sbadmin_list_view_config=(),
        ordering=(),
    ):
        self.sbadmin_list_display = sbadmin_list_display
        self.sbadmin_list_view_config = sbadmin_list_view_config
        self.ordering = ordering


def _field(name, *, filter_field=None, with_filter=True, filter_disabled=False):
    return SBAdminField(
        name=name,
        filter_field=filter_field,
        filter_widget=_SentinelFilterWidget() if with_filter else None,
        filter_disabled=filter_disabled,
    )


class TestW001DuplicateFilterField(TestCase):
    def test_unique_filter_fields_no_warning(self):
        admin = _FakeAdmin(
            sbadmin_list_display=(_field("status"), _field("category")),
        )
        self.assertEqual(check_duplicate_filter_field_for_admin(admin), [])

    def test_explicit_filter_field_collides_with_default(self):
        # The ticket_browser_admin.py footgun: SBAdminField(name="id") and
        # SBAdminField(name="id_list", filter_field="id") both render input
        # name="id". Exercises both branches of `_effective_filter_field`.
        admin = _FakeAdmin(
            sbadmin_list_display=(
                _field("id"),
                _field("id_list", filter_field="id"),
            ),
        )
        result = check_duplicate_filter_field_for_admin(admin)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sbadmin.W001")
        self.assertIn("filter_field='id'", result[0].msg)
        self.assertIn("id_list", result[0].msg)

    def test_non_filtering_fields_skipped(self):
        # Both gates in `_has_filter` (filter_disabled, missing widget) should
        # prevent a collision from being reported.
        for label, second in (
            ("filter_disabled", _field("id_list", filter_field="id", filter_disabled=True)),
            ("no_widget", _field("id_list", filter_field="id", with_filter=False)),
        ):
            with self.subTest(skip=label):
                admin = _FakeAdmin(sbadmin_list_display=(_field("id"), second))
                self.assertEqual(check_duplicate_filter_field_for_admin(admin), [])


class TestW002ViewConfigFilterKeys(TestCase):
    def test_valid_keys_no_warning(self):
        # Covers all three valid spellings in one fixture: default-name key,
        # explicit-filter_field key, and plain-string display entry.
        admin = _FakeAdmin(
            sbadmin_list_display=(
                _field("status"),
                _field("author_display", filter_field="author"),
                "title",
            ),
            sbadmin_list_view_config=[
                {
                    "name": "Open",
                    "url_params": {
                        "filterData": {"status": "", "author": "42", "title": ""},
                    },
                }
            ],
        )
        self.assertEqual(check_view_config_filter_keys_for_admin(admin), [])

    def test_unknown_key_warns(self):
        admin = _FakeAdmin(
            sbadmin_list_display=(_field("status"),),
            sbadmin_list_view_config=[
                {
                    "name": "Open",
                    "url_params": {"filterData": {"bogus": ""}},
                }
            ],
        )
        result = check_view_config_filter_keys_for_admin(admin)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sbadmin.W002")
        self.assertIn("'bogus'", result[0].msg)


class TestW003OrderingColumns(TestCase):
    def test_known_field_in_ordering_no_warning(self):
        # Mix SBAdminField + plain-string entry; cover the "-" prefix strip.
        admin = _FakeAdmin(
            sbadmin_list_display=(_field("priority"), "created_at"),
            ordering=("-priority", "created_at"),
        )
        self.assertEqual(check_ordering_columns_for_admin(admin), [])

    def test_missing_field_warns(self):
        # The queue_browser_admin.py footgun. Also asserts the "-" prefix is
        # stripped from the reported field name.
        admin = _FakeAdmin(
            sbadmin_list_display=(_field("display_name"),),
            ordering=("-rank",),
        )
        result = check_ordering_columns_for_admin(admin)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "sbadmin.W003")
        self.assertIn("'rank'", result[0].msg)
        self.assertNotIn("'-rank'", result[0].msg)

    def test_special_lookups_skipped(self):
        # Related lookups and random ordering aren't representable as
        # Tabulator column fields; they're explicitly out of scope.
        for raw in ("category__name", "?"):
            with self.subTest(raw=raw):
                admin = _FakeAdmin(
                    sbadmin_list_display=(_field("title"),),
                    ordering=(raw,),
                )
                self.assertEqual(check_ordering_columns_for_admin(admin), [])
