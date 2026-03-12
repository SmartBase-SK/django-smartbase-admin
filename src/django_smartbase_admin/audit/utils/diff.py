"""
Diff utilities for audit logging.
Computes differences between before and after states.
"""

from typing import Any

from django_smartbase_admin.audit.utils.serialization import _json_safe


def compute_diff(
    before: dict[str, Any],
    after: dict[str, Any],
    display_before: dict[str, str] | None = None,
    display_after: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Compute the difference between two dictionaries.

    Args:
        before: Dictionary of field values before the change.
        after: Dictionary of field values after the change.
        display_before: Optional dictionary of display values for before state.
        display_after: Optional dictionary of display values for after state.

    Returns:
        Dictionary with changed fields as keys, containing:
        - old: The old value
        - new: The new value
        - old_display: Optional display value for old (if different from old)
        - new_display: Optional display value for new (if different from new)
    """
    display_before = display_before or {}
    display_after = display_after or {}
    changes = {}

    all_keys = set(before.keys()) | set(after.keys())

    for key in all_keys:
        old_value = before.get(key)
        new_value = after.get(key)

        if old_value != new_value:
            change = {
                "old": old_value,
                "new": new_value,
            }

            old_display = display_before.get(key)
            new_display = display_after.get(key)

            if old_display and str(old_display) != str(old_value):
                change["old_display"] = old_display

            if new_display and str(new_display) != str(new_value):
                change["new_display"] = new_display

            changes[key] = change

    return changes


def compute_bulk_diff(
    objects_before: list[dict[str, Any]],
    update_values: dict[str, Any],
    id_field: str = "id",
) -> dict[str, dict[str, Any]]:
    """
    Compute a compressed diff for bulk update operations.

    Groups objects by their old values for each changed field.

    Args:
        objects_before: List of dictionaries representing objects before update.
        update_values: Dictionary of fields being updated with their new values.
        id_field: The field name for object IDs.

    Returns:
        Dictionary with changed fields as keys, containing:
        - new: The new value being set
        - by_old: Dictionary mapping old values to lists of affected IDs
    """
    changes = {}

    for field_name, new_value in update_values.items():
        by_old = {}

        for obj in objects_before:
            obj_id = obj.get(id_field)
            old_value = obj.get(field_name)

            old_key = str(old_value) if old_value is not None else "__null__"

            if old_key not in by_old:
                by_old[old_key] = []
            by_old[old_key].append(obj_id)

        if by_old:
            changes[field_name] = {
                "new": _json_safe(new_value),
                "by_old": by_old,
            }

    return changes


def compute_bulk_snapshot(
    objects_before: list[dict[str, Any]],
    fields: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Compute a compressed snapshot for bulk operations.

    For each field, stores unique values and which objects had them.

    Args:
        objects_before: List of dictionaries representing objects.
        fields: List of field names to include in snapshot.

    Returns:
        Dictionary with field names as keys, containing:
        - unique_values: List of unique values for this field
        - displays: Optional dictionary mapping values to display strings
    """
    snapshot = {}

    for field_name in fields:
        values_set = set()
        for obj in objects_before:
            value = obj.get(field_name)
            if isinstance(value, list):
                value = tuple(value)
            values_set.add(value)

        unique_values = [list(v) if isinstance(v, tuple) else v for v in values_set]

        snapshot[field_name] = {
            "unique_values": unique_values,
        }

    return snapshot
