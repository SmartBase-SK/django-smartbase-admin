"""Unit tests for ``write_widget_input`` — the per-widget POST encoder.

Drives the encoder directly against real widget instances so each
branch (file, ``MultiWidget``, ``SelectMultiple``, autocomplete, plain)
is exercised without standing up a full admin form. The integration
tests in ``test_update_detail`` and ``test_create_object`` cover the
common plain + autocomplete + checkbox paths via real
``_changeform_view`` round-trips; the branches here are the ones a
fixture-only test can't reach because the bundled admins
(``Folder`` / ``FolderPermission``) don't declare any file,
multi-select, or split-datetime fields.

Every test asserts the full round-trip through the widget's own
``value_from_datadict`` — encoder output is only "correct" if Django's
own read side recovers the original Python value.
"""

from __future__ import annotations

from datetime import date, datetime, time
from unittest import TestCase

from django.forms.widgets import (
    CheckboxInput,
    CheckboxSelectMultiple,
    ClearableFileInput,
    FileInput,
    SelectMultiple,
    SplitDateTimeWidget,
    TextInput,
)
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict

from django.test import RequestFactory, override_settings

from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.mcp.form_encoding import write_widget_input
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService


def _empty_qd() -> QueryDict:
    return QueryDict(mutable=True)


class WritePlainWidgetTests(TestCase):
    def test_string_round_trips_through_value_from_datadict(self):
        qd = _empty_qd()
        widget = TextInput()
        write_widget_input(qd, "name", widget, "renamed")
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "name"), "renamed"
        )

    def test_native_bool_round_trips_unchanged(self):
        """No string coercion — ``QueryDict`` keeps ``True`` as a bool."""
        qd = _empty_qd()
        widget = TextInput()
        write_widget_input(qd, "active", widget, True)
        self.assertIs(widget.value_from_datadict(qd, MultiValueDict(), "active"), True)

    def test_native_int_round_trips_unchanged(self):
        qd = _empty_qd()
        widget = TextInput()
        write_widget_input(qd, "n", widget, 42)
        recovered = widget.value_from_datadict(qd, MultiValueDict(), "n")
        self.assertEqual(recovered, 42)
        self.assertIsInstance(recovered, int)

    def test_envelope_is_unwrapped(self):
        """``{"value", "label"}`` from fetch_detail round-trips back to its pk."""
        qd = _empty_qd()
        widget = TextInput()
        write_widget_input(qd, "parent", widget, {"value": 7, "label": "Parent"})
        self.assertEqual(widget.value_from_datadict(qd, MultiValueDict(), "parent"), 7)


class WriteCheckboxInputTests(TestCase):
    """Pin standard-checkbox encoding + ``value_from_datadict`` round-trip.

    The integration tests already exercise this path via the inline
    ``everybody=True`` write, but those go through the full admin
    pipeline. Asserting on a bare ``CheckboxInput`` here documents the
    encoder's contract directly: write ``True`` / ``False`` natively
    and let ``CheckboxInput.value_from_datadict`` coerce on read.
    """

    def test_true_round_trips_through_value_from_datadict(self):
        qd = _empty_qd()
        widget = CheckboxInput()
        write_widget_input(qd, "active", widget, True)
        self.assertIs(widget.value_from_datadict(qd, MultiValueDict(), "active"), True)

    def test_false_round_trips_through_value_from_datadict(self):
        qd = _empty_qd()
        widget = CheckboxInput()
        write_widget_input(qd, "active", widget, False)
        # ``False`` reads back as ``False`` whether the key is present
        # (this path) or absent — ``CheckboxInput.value_from_datadict``
        # treats both the same. Pinning the present-key path explicitly.
        self.assertIs(widget.value_from_datadict(qd, MultiValueDict(), "active"), False)

    def test_none_round_trips_to_false(self):
        qd = _empty_qd()
        widget = CheckboxInput()
        write_widget_input(qd, "active", widget, None)
        self.assertIs(widget.value_from_datadict(qd, MultiValueDict(), "active"), False)


class WriteFileWidgetTests(TestCase):
    def test_file_input_omits_key(self):
        """Absence of the key means 'no upload, keep current value'."""
        qd = _empty_qd()
        write_widget_input(qd, "doc", FileInput(), "anything")
        self.assertNotIn("doc", qd)

    def test_clearable_file_input_omits_key(self):
        qd = _empty_qd()
        write_widget_input(qd, "doc", ClearableFileInput(), None)
        self.assertNotIn("doc", qd)


class WriteSelectMultipleTests(TestCase):
    def test_list_round_trips_through_value_from_datadict(self):
        qd = _empty_qd()
        widget = SelectMultiple()
        write_widget_input(qd, "tags", widget, [1, 2, 3])
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "tags"), [1, 2, 3]
        )

    def test_none_round_trips_to_empty_list(self):
        qd = _empty_qd()
        widget = SelectMultiple()
        write_widget_input(qd, "tags", widget, None)
        self.assertEqual(widget.value_from_datadict(qd, MultiValueDict(), "tags"), [])

    def test_empty_string_round_trips_to_empty_list(self):
        qd = _empty_qd()
        widget = SelectMultiple()
        write_widget_input(qd, "tags", widget, "")
        self.assertEqual(widget.value_from_datadict(qd, MultiValueDict(), "tags"), [])

    def test_checkbox_select_multiple_round_trips(self):
        qd = _empty_qd()
        widget = CheckboxSelectMultiple()
        write_widget_input(qd, "tags", widget, [10, 20])
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "tags"), [10, 20]
        )


class WriteMultiWidgetTests(TestCase):
    def test_split_datetime_round_trips_through_value_from_datadict(self):
        qd = _empty_qd()
        widget = SplitDateTimeWidget()
        original = datetime(2024, 5, 26, 14, 30)
        write_widget_input(qd, "when", widget, original)
        # ``MultiWidget.value_from_datadict`` returns ``[date, time]``;
        # ``SplitDateTimeField.compress`` would reassemble it on the
        # field side. The encoder's contract stops at the per-subwidget
        # split here.
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "when"),
            [date(2024, 5, 26), time(14, 30)],
        )

    def test_split_datetime_none_round_trips_to_none_subvalues(self):
        qd = _empty_qd()
        widget = SplitDateTimeWidget()
        write_widget_input(qd, "when", widget, None)
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "when"), [None, None]
        )

    def test_split_datetime_accepts_naive_iso_string(self):
        qd = _empty_qd()
        widget = SplitDateTimeWidget()
        write_widget_input(qd, "when", widget, "2024-05-26T14:30:00")
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "when"),
            [date(2024, 5, 26), time(14, 30)],
        )

    @override_settings(TIME_ZONE="UTC")
    def test_split_datetime_accepts_tz_aware_iso_string(self):
        # tz-aware ISO (what fetch_* returns) must be accepted on the way in,
        # not rejected — localized to wall-clock for the date/time subwidgets.
        # Pin TIME_ZONE=UTC so the Z value localizes 1:1 (the localization
        # itself is covered by it converting offsets at all).
        qd = _empty_qd()
        widget = SplitDateTimeWidget()
        write_widget_input(qd, "when", widget, "2024-05-26T14:30:00Z")
        self.assertEqual(
            widget.value_from_datadict(qd, MultiValueDict(), "when"),
            [date(2024, 5, 26), time(14, 30)],
        )


class WriteAutocompleteTests(TestCase):
    """Round-trip against the real ``SBAdminAutocompleteWidget``.

    ``parse_value_from_input`` is the read-side contract, and it diverges
    between ``multiselect=True`` (returns ``list``) and
    ``multiselect=False`` (unwraps via ``next(iter(...), None)``). Both
    paths matter for MCP write correctness — single FK writes vs. M2M
    writes — so both are pinned here.

    ``filer.Folder`` is the cheapest in-tree model the test settings
    already register; the widget never hits the DB during
    ``value_from_datadict`` outside a validation context, so no fixtures
    are needed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # SBAdminAutocompleteWidget.value_from_datadict reads the active
        # request via SBAdminThreadLocalService; supply a bare one.
        SBAdminThreadLocalService.set_request(request=RequestFactory().get("/"))
        from filer.models import Folder

        cls.single = SBAdminAutocompleteWidget(
            form_field=None, model=Folder, multiselect=False
        )
        cls.multi = SBAdminAutocompleteWidget(
            form_field=None, model=Folder, multiselect=True
        )

    @classmethod
    def tearDownClass(cls):
        SBAdminThreadLocalService.clear_request()
        super().tearDownClass()

    def _empty(self) -> MultiValueDict:
        return MultiValueDict()

    def test_single_scalar_round_trips(self):
        qd = _empty_qd()
        write_widget_input(qd, "fk", self.single, 5)
        self.assertEqual(self.single.value_from_datadict(qd, self._empty(), "fk"), 5)

    def test_single_envelope_round_trips_to_pk(self):
        qd = _empty_qd()
        write_widget_input(qd, "fk", self.single, {"value": 7, "label": "X"})
        self.assertEqual(self.single.value_from_datadict(qd, self._empty(), "fk"), 7)

    def test_single_none_round_trips_to_none(self):
        qd = _empty_qd()
        write_widget_input(qd, "fk", self.single, None)
        self.assertIsNone(self.single.value_from_datadict(qd, self._empty(), "fk"))

    def test_multi_list_round_trips(self):
        qd = _empty_qd()
        write_widget_input(qd, "fk", self.multi, [1, 2])
        self.assertEqual(
            self.multi.value_from_datadict(qd, self._empty(), "fk"), [1, 2]
        )

    def test_multi_envelope_list_round_trips_to_pks(self):
        qd = _empty_qd()
        write_widget_input(
            qd,
            "fk",
            self.multi,
            [{"value": 1, "label": "A"}, {"value": 2, "label": "B"}],
        )
        self.assertEqual(
            self.multi.value_from_datadict(qd, self._empty(), "fk"), [1, 2]
        )

    def test_multi_none_round_trips_to_none(self):
        # parse_value_from_input("") returns "" — empty M2M write is
        # signalled by the queryset stage, not the widget.
        qd = _empty_qd()
        write_widget_input(qd, "fk", self.multi, None)
        self.assertIsNone(self.multi.value_from_datadict(qd, self._empty(), "fk"))
