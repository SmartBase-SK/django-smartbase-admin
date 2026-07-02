from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from django.utils import timezone

from django_smartbase_admin.engine.filter_widgets import DateFilterWidget


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
