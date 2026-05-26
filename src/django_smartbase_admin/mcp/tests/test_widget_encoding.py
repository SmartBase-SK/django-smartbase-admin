"""Unit tests for ``_write_widget_input`` — the per-widget POST encoder.

Drives the encoder directly against synthetic widgets so each branch
(file, MultiWidget, SelectMultiple, autocomplete, plain) is exercised
without standing up a full admin form. The integration tests in
``test_update_detail`` and ``test_create_object`` cover the common
plain + autocomplete + checkbox paths via real ``_changeform_view``
round-trips; the branches here are the ones a fixture-only test can't
reach because the bundled admins (``Folder`` / ``FolderPermission``)
don't declare any file, multi-select, or split-datetime fields.
"""

from __future__ import annotations

from datetime import date, datetime, time
from unittest import TestCase

from django.forms.widgets import (
    CheckboxSelectMultiple,
    ClearableFileInput,
    FileInput,
    SelectMultiple,
    SplitDateTimeWidget,
    TextInput,
)
from django.http import QueryDict

from django_smartbase_admin.engine.filter_widgets import AutocompleteParseMixin
from django_smartbase_admin.mcp.service import _write_widget_input


class _FakeAutocomplete(AutocompleteParseMixin):
    """Bare ``AutocompleteParseMixin`` consumer for branch testing.

    The real autocomplete widget pulls request state from
    ``SBAdminThreadLocalService`` during ``value_from_datadict``; the
    encoder only checks ``isinstance(widget, AutocompleteParseMixin)``
    so this stub is enough to drive the branch.
    """


def _empty_qd() -> QueryDict:
    return QueryDict(mutable=True)


class WritePlainWidgetTests(TestCase):
    def test_native_value_passes_through_unchanged(self):
        qd = _empty_qd()
        _write_widget_input(qd, "name", TextInput(), "renamed")
        self.assertEqual(qd["name"], "renamed")

    def test_native_bool_stored_as_bool(self):
        qd = _empty_qd()
        _write_widget_input(qd, "active", TextInput(), True)
        self.assertIs(qd["active"], True)

    def test_native_int_stored_as_int(self):
        qd = _empty_qd()
        _write_widget_input(qd, "n", TextInput(), 42)
        self.assertEqual(qd["n"], 42)
        self.assertIsInstance(qd["n"], int)

    def test_envelope_is_unwrapped(self):
        """``{"value", "label"}`` from fetch_detail round-trips back to its pk."""
        qd = _empty_qd()
        _write_widget_input(qd, "parent", TextInput(), {"value": 7, "label": "Parent"})
        self.assertEqual(qd["parent"], 7)


class WriteFileWidgetTests(TestCase):
    def test_file_input_omits_key(self):
        """Absence of the key means 'no upload, keep current value'."""
        qd = _empty_qd()
        _write_widget_input(qd, "doc", FileInput(), "anything")
        self.assertNotIn("doc", qd)

    def test_clearable_file_input_omits_key(self):
        qd = _empty_qd()
        _write_widget_input(qd, "doc", ClearableFileInput(), None)
        self.assertNotIn("doc", qd)


class WriteSelectMultipleTests(TestCase):
    def test_list_value_stored_as_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "tags", SelectMultiple(), [1, 2, 3])
        self.assertEqual(qd.getlist("tags"), [1, 2, 3])

    def test_none_becomes_empty_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "tags", SelectMultiple(), None)
        self.assertEqual(qd.getlist("tags"), [])

    def test_empty_string_becomes_empty_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "tags", SelectMultiple(), "")
        self.assertEqual(qd.getlist("tags"), [])

    def test_checkbox_select_multiple_uses_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "tags", CheckboxSelectMultiple(), [10, 20])
        self.assertEqual(qd.getlist("tags"), [10, 20])


class WriteMultiWidgetTests(TestCase):
    def test_split_datetime_decomposes_into_subkeys(self):
        qd = _empty_qd()
        widget = SplitDateTimeWidget()
        _write_widget_input(qd, "when", widget, datetime(2024, 5, 26, 14, 30))
        # ``SplitDateTimeWidget`` reads ``name_0`` (date) + ``name_1`` (time).
        self.assertEqual(qd["when_0"], date(2024, 5, 26))
        self.assertEqual(qd["when_1"], time(14, 30))

    def test_split_datetime_none_writes_none_subvalues(self):
        qd = _empty_qd()
        _write_widget_input(qd, "when", SplitDateTimeWidget(), None)
        self.assertIsNone(qd["when_0"])
        self.assertIsNone(qd["when_1"])


class WriteAutocompleteTests(TestCase):
    def test_scalar_wrapped_in_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "fk", _FakeAutocomplete(), 5)
        self.assertEqual(qd["fk"], [5])

    def test_list_value_passes_through(self):
        qd = _empty_qd()
        _write_widget_input(qd, "fk", _FakeAutocomplete(), [1, 2])
        self.assertEqual(qd["fk"], [1, 2])

    def test_none_becomes_empty_list(self):
        qd = _empty_qd()
        _write_widget_input(qd, "fk", _FakeAutocomplete(), None)
        self.assertEqual(qd["fk"], [])

    def test_envelope_list_unwrapped_to_pks(self):
        """A list of ``{"value", "label"}`` envelopes echoed from fetch_detail."""
        qd = _empty_qd()
        _write_widget_input(
            qd,
            "fk",
            _FakeAutocomplete(),
            [{"value": 1, "label": "A"}, {"value": 2, "label": "B"}],
        )
        self.assertEqual(qd["fk"], [1, 2])
