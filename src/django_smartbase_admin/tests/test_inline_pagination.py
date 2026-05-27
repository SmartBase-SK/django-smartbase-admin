from django.test import SimpleTestCase

from django_smartbase_admin.templatetags.sb_paginated_inline import (
    build_tabulator_style_page_items,
)


def _page_numbers(items):
    return [item["number"] for item in items if item["kind"] == "page"]


class BuildTabulatorStylePageItemsTests(SimpleTestCase):
    def test_shows_all_pages_when_within_active_range(self):
        items = build_tabulator_style_page_items(current_page=2, max_page=6)
        self.assertEqual(_page_numbers(items), [1, 2, 3, 4, 5, 6])

    def test_start_shows_first_active_range_and_last_page(self):
        items = build_tabulator_style_page_items(current_page=2, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 2, 3, 4, 5, 20])
        self.assertEqual(sum(item["kind"] == "ellipsis" for item in items), 1)

    def test_middle_shows_five_centered_pages(self):
        items = build_tabulator_style_page_items(current_page=10, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 8, 9, 10, 11, 12, 20])

    def test_end_shows_last_active_range_without_trailing_last_duplicate(self):
        items = build_tabulator_style_page_items(current_page=19, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 16, 17, 18, 19, 20])
        self.assertEqual(sum(item["kind"] == "ellipsis" for item in items), 1)

    def test_at_most_five_numbered_buttons_in_middle(self):
        items = build_tabulator_style_page_items(current_page=10, max_page=50)
        page_items = [
            item
            for item in items
            if item["kind"] == "page" and item["number"] not in (1, 50)
        ]
        self.assertEqual(len(page_items), 5)
