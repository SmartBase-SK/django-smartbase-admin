"""The list/export sort only orders by declared columns (and the pk)."""

from types import SimpleNamespace

from django.test import SimpleTestCase
from filer.models import Folder

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction


def _list_action(sort, ordering=None):
    action = object.__new__(SBAdminListAction)
    action.table_params = {"sort": sort}
    action.column_fields = [
        SimpleNamespace(field="name"),
        SimpleNamespace(field="rank_display"),
    ]
    action.view = SimpleNamespace(
        model=Folder, get_list_ordering=lambda request: ordering
    )
    action.threadsafe_request = None
    return action


class ListSortTests(SimpleTestCase):
    def test_declared_columns_and_pk_sort(self):
        action = _list_action(
            [
                {"field": "name", "dir": "desc"},
                {"field": "rank_display", "dir": "asc"},
                {"field": "id", "dir": "asc"},
            ]
        )
        self.assertEqual(
            action.get_order_by_from_request(), ["-name", "rank_display", "id"]
        )

    def test_undeclared_fields_are_dropped(self):
        # e.g. a related salary the list never shows: sorting by it would leak its ranking.
        action = _list_action(
            [
                {"field": "owner__password", "dir": "desc"},
                {"field": "name", "dir": "asc"},
                "junk",
            ]
        )
        self.assertEqual(action.get_order_by_from_request(), ["name"])

    def test_only_undeclared_fields_fall_back_to_the_default_ordering(self):
        action = _list_action(
            [{"field": "owner__password", "dir": "asc"}], ordering=["-name"]
        )
        self.assertEqual(action.get_order_by_from_request(), ["-name"])
