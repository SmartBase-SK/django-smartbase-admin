from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.db.models import Q
from django.utils import timezone

from django_smartbase_admin.engine.filter_widgets import (
    BooleanFilterWidget,
    DateFilterWidget,
)


class TestDateFilterWidget(TestCase):
    def test_day_shortcut_bounds_start_at_midnight(self):
        now = timezone.make_aware(datetime(2026, 6, 22, 9, 14, 22))

        with patch(
            "django_smartbase_admin.engine.filter_widgets.timezone.now",
            return_value=now,
        ):
            date_from, date_to = DateFilterWidget.get_range_from_value([-30, 0])

        self.assertEqual(date_from, timezone.make_aware(datetime(2026, 5, 23, 0, 0, 0)))
        self.assertEqual(date_to, timezone.make_aware(datetime(2026, 6, 22, 0, 0, 0)))

    def test_range_ends_before_the_day_after_its_last_day(self):
        widget = DateFilterWidget()
        widget.field = SimpleNamespace(filter_field="posted")
        query = widget.get_base_filter_query_for_parsed_value(
            None, DateFilterWidget.get_range_from_value(["2026-09-01", "2026-09-30"])
        )

        self.assertEqual(
            query,
            Q(posted__gte=datetime(2026, 9, 1)) & Q(posted__lt=datetime(2026, 10, 1)),
        )


class TestBooleanFilterWidget(TestCase):
    def test_parses_every_shape_its_own_markup_produces(self):
        """The radio renders the (True, False) choices as str(True) / str(False), which json.loads
        cannot read — "False" would stay a string and read as truthy in a filter_query_lambda.
        """
        widget = BooleanFilterWidget()

        parsed = {
            raw: widget.parse_value_from_input(None, raw)
            for raw in ("True", "False", "true", "false")
        }

        self.assertEqual(
            parsed, {"True": True, "False": False, "true": True, "false": False}
        )

    def test_leaves_no_value_alone(self):
        widget = BooleanFilterWidget()

        self.assertIsNone(widget.parse_value_from_input(None, None))
        self.assertEqual(widget.parse_value_from_input(None, ""), "")
