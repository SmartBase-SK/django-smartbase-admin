"""Unit tests for diff utility functions."""

from unittest import TestCase

from django_smartbase_admin.audit.utils.diff import (
    compute_bulk_diff,
    compute_bulk_snapshot,
    compute_diff,
)


class TestComputeDiff(TestCase):
    """Tests for compute_diff."""

    def test_detects_changed_fields(self):
        before = {"name": "Old", "status": "active"}
        after = {"name": "New", "status": "active"}
        result = compute_diff(before, after)
        self.assertEqual(result, {"name": {"old": "Old", "new": "New"}})

    def test_detects_added_fields(self):
        before = {"name": "A"}
        after = {"name": "A", "email": "a@b.com"}
        result = compute_diff(before, after)
        self.assertEqual(result, {"email": {"old": None, "new": "a@b.com"}})

    def test_detects_removed_fields(self):
        before = {"name": "A", "email": "a@b.com"}
        after = {"name": "A"}
        result = compute_diff(before, after)
        self.assertEqual(result, {"email": {"old": "a@b.com", "new": None}})

    def test_empty_on_no_changes(self):
        data = {"name": "Same", "count": 5}
        result = compute_diff(data, data)
        self.assertEqual(result, {})

    def test_includes_display_values_when_different(self):
        before = {"author": 1}
        after = {"author": 2}
        display_before = {"author": "Alice"}
        display_after = {"author": "Bob"}
        result = compute_diff(before, after, display_before, display_after)
        self.assertEqual(result["author"]["old"], 1)
        self.assertEqual(result["author"]["new"], 2)
        self.assertEqual(result["author"]["old_display"], "Alice")
        self.assertEqual(result["author"]["new_display"], "Bob")

    def test_omits_display_when_same_as_value(self):
        before = {"name": "Old"}
        after = {"name": "New"}
        display_before = {"name": "Old"}
        display_after = {"name": "New"}
        result = compute_diff(before, after, display_before, display_after)
        self.assertNotIn("old_display", result["name"])
        self.assertNotIn("new_display", result["name"])


class TestComputeBulkDiff(TestCase):
    """Tests for compute_bulk_diff."""

    def test_groups_by_old_value(self):
        objects = [
            {"id": 1, "status": "draft"},
            {"id": 2, "status": "draft"},
            {"id": 3, "status": "published"},
        ]
        result = compute_bulk_diff(objects, {"status": "archived"})
        self.assertEqual(result["status"]["new"], "archived")
        self.assertEqual(set(result["status"]["by_old"]["draft"]), {1, 2})
        self.assertEqual(result["status"]["by_old"]["published"], [3])

    def test_handles_none_values(self):
        objects = [
            {"id": 1, "category": None},
            {"id": 2, "category": "tech"},
        ]
        result = compute_bulk_diff(objects, {"category": "science"})
        self.assertEqual(result["category"]["new"], "science")
        self.assertEqual(result["category"]["by_old"]["__null__"], [1])
        self.assertEqual(result["category"]["by_old"]["tech"], [2])

    def test_multiple_fields(self):
        objects = [
            {"id": 1, "active": True, "role": "user"},
            {"id": 2, "active": False, "role": "user"},
        ]
        result = compute_bulk_diff(objects, {"active": True, "role": "admin"})
        self.assertIn("active", result)
        self.assertIn("role", result)
        self.assertEqual(result["role"]["new"], "admin")


class TestComputeBulkSnapshot(TestCase):
    """Tests for compute_bulk_snapshot."""

    def test_captures_unique_values(self):
        objects = [
            {"id": 1, "status": "draft"},
            {"id": 2, "status": "draft"},
            {"id": 3, "status": "published"},
        ]
        result = compute_bulk_snapshot(objects, ["status"])
        self.assertEqual(set(result["status"]["unique_values"]), {"draft", "published"})

    def test_handles_multiple_fields(self):
        objects = [
            {"id": 1, "status": "active", "role": "user"},
            {"id": 2, "status": "inactive", "role": "admin"},
        ]
        result = compute_bulk_snapshot(objects, ["status", "role"])
        self.assertIn("status", result)
        self.assertIn("role", result)
        self.assertEqual(set(result["status"]["unique_values"]), {"active", "inactive"})
        self.assertEqual(set(result["role"]["unique_values"]), {"user", "admin"})
