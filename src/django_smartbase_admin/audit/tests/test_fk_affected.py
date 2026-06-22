"""``_extract_fk_affected`` must keep FK pks as they arrive (already
JSON-safe from serialization): int pks stay int, and non-int pks (UUID /
char) are kept as their string form instead of crashing on ``int(...)`` —
the regression that logged a noisy "Failed to create audit log" whenever a
FK pointed at a UUID-keyed model.
"""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.test import SimpleTestCase

from django_smartbase_admin.audit.manager import _extract_fk_affected

# ``Permission.content_type`` is a ForeignKey; the related model's own pk
# type is irrelevant to the bug — only the value handed in matters.


class ExtractFkAffectedTests(SimpleTestCase):
    def test_uuid_string_pk_kept_not_cast_to_int(self):
        uid = "aa57f521-1c2b-4f3a-9d4e-5f6a7b8c9d0e"
        affected = _extract_fk_affected(
            Permission,
            {"content_type": {"old": None, "new": uid, "new_display": "Queue X"}},
        )
        self.assertEqual(
            affected,
            [{"ct": "contenttypes.contenttype", "id": uid, "repr": "Queue X"}],
        )

    def test_integer_pk_preserved_as_int(self):
        affected = _extract_fk_affected(
            Permission,
            {
                "content_type": {
                    "old": 7,
                    "new": 9,
                    "old_display": "A",
                    "new_display": "B",
                }
            },
        )
        self.assertEqual([a["id"] for a in affected], [7, 9])
        self.assertTrue(all(isinstance(a["id"], int) for a in affected))
