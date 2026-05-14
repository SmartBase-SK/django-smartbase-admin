"""Django system checks for SBAdmin admins.

These run on ``manage.py check``, ``runserver``, and during CI, and catch
configuration footguns that otherwise surface only at runtime — usually as a
spurious "view changed" ``*`` next to a saved view tab or as a silently
disabled filter.

Currently checked:

* ``sbadmin.W001`` — two ``SBAdminField`` entries on the same admin resolve to
  the same ``filter_field``. The framework renders both as a form input with
  the same ``name``/``id`` and JS only ever sees the first one, so the second
  filter is effectively dead.

* ``sbadmin.W002`` — a key in ``sbadmin_list_view_config["url_params"]
  ["filterData"]`` doesn't correspond to any ``SBAdminField``'s effective
  ``filter_field``. The frontend then can't find the matching input during
  ``loadFromUrl``, leaves it disabled, drops it from ``FormData``, and the
  view tab renders with a spurious ``*``.

* ``sbadmin.W003`` — a column-side name in ``ordering`` (after stripping the
  ``-`` prefix) isn't present as an ``SBAdminField`` in
  ``sbadmin_list_display``. Tabulator silently drops the entry from
  ``tableInitialSort``, the actual sort then differs from initial,
  ``tableData.sort`` leaks into ``getUrlParamsForSave()``, and the view tab
  renders with a spurious ``*``. The check skips related lookups
  (``foo__bar``) because Tabulator can't represent them as a column field
  anyway and the right fix is widget-specific.

All three are warnings rather than errors; misconfigured admins still render,
just with the symptoms above.
"""

from __future__ import annotations

from django.core.checks import Tags, Warning, register

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField


def _iter_sbadmin_fields(admin):
    """Yield ``SBAdminField`` instances from an admin's ``sbadmin_list_display``.

    Plain-string entries are skipped — they refer directly to model fields and
    can't produce the misconfigurations these checks look for.
    """
    for entry in getattr(admin, "sbadmin_list_display", None) or ():
        if isinstance(entry, SBAdminField):
            yield entry


def _effective_filter_field(field: SBAdminField) -> str:
    """Approximate ``SBAdminField.filter_field`` without running ``init_field_static``.

    The runtime defaulting cascade ends in ``filter_field = filter_field or
    name``; that approximation matches ~all real configurations. The few
    branches that pick a different default (m2m / view_method with
    ``admin_order_field``) are edge cases where this check would either still
    be correct or would emit a false positive — never miss a real bug.
    """
    return field.filter_field or field.name


def _has_filter(field: SBAdminField) -> bool:
    """Whether a field will render a filter input at runtime.

    ``SBAdminField.init_filter_for_field`` (in ``engine/field.py``) always
    attaches a filter widget unless ``filter_disabled=True`` — falling back
    through ``StringFilterWidget`` / ``BooleanFilterWidget`` /
    ``DateFilterWidget`` / ``AutocompleteFilterWidget`` based on the model
    field, then to a bare ``StringFilterWidget()`` as a last resort. Anything
    not explicitly disabled therefore renders a filter input, which is what
    the W001/W002 collision and url-key checks need to know.
    """
    return not getattr(field, "filter_disabled", False)


def _admin_targets():
    """All admins registered with ``sb_admin_site`` that expose a list view."""
    try:
        registry = sb_admin_site._registry
    except Exception:
        return []
    targets = []
    for admin in registry.values():
        # Skip third-party admins and anything that's clearly not an SBAdmin
        # list view (audit, fake inlines, etc.). Cheapest reliable test: does
        # the class declare any of the attributes we want to check?
        if not any(
            hasattr(admin, attr)
            for attr in (
                "sbadmin_list_display",
                "sbadmin_list_view_config",
                "ordering",
            )
        ):
            continue
        targets.append(admin)
    return targets


def check_duplicate_filter_field_for_admin(admin):
    """Per-admin implementation of ``sbadmin.W001``. Exposed for unit tests."""
    warnings = []
    seen: dict[str, SBAdminField] = {}
    for field in _iter_sbadmin_fields(admin):
        if not _has_filter(field):
            continue
        key = _effective_filter_field(field)
        other = seen.get(key)
        if other is not None:
            warnings.append(
                Warning(
                    (
                        f"{admin.__class__.__name__}: SBAdminField "
                        f"{field.name!r} and {other.name!r} resolve to the "
                        f"same filter_field={key!r}. Both render a form "
                        "input with the same name; JS reaches only the "
                        "first, so the second filter is dead and any "
                        "sbadmin_list_view_config key for it produces a "
                        "spurious '*' on the tab."
                    ),
                    hint=(
                        "Remove the redundant filter_field=… on one of "
                        "the fields (let it default to its name) or "
                        "rename so the two filter inputs are distinct."
                    ),
                    obj=admin.__class__,
                    id="sbadmin.W001",
                )
            )
            continue
        seen[key] = field
    return warnings


def check_view_config_filter_keys_for_admin(admin):
    """Per-admin implementation of ``sbadmin.W002``. Exposed for unit tests."""
    warnings = []
    view_config = getattr(admin, "sbadmin_list_view_config", None) or ()
    if not view_config:
        return warnings
    # Accept both effective filter_field and SBAdminField.name as valid keys;
    # the framework reads filter_field at runtime, but admins that author
    # configs by hand often forget that distinction. Either works in practice
    # because the framework also uses name for the form input id when
    # filter_field defaults to name. The dangerous case is a key that matches
    # NEITHER.
    valid_keys: set[str] = set()
    for field in _iter_sbadmin_fields(admin):
        if not _has_filter(field):
            continue
        valid_keys.add(_effective_filter_field(field))
        if field.name:
            valid_keys.add(field.name)
    # Plain-string entries in sbadmin_list_display also produce filter inputs
    # named after themselves.
    for entry in getattr(admin, "sbadmin_list_display", None) or ():
        if isinstance(entry, str):
            valid_keys.add(entry)

    for cfg in view_config:
        if not isinstance(cfg, dict):
            continue
        filter_data = (cfg.get("url_params") or {}).get("filterData") or {}
        for key in filter_data:
            if key in valid_keys:
                continue
            warnings.append(
                Warning(
                    (
                        f"{admin.__class__.__name__}: sbadmin_list_view_config "
                        f"tab {cfg.get('name')!r} references filterData "
                        f"key {key!r} that doesn't match any SBAdminField's "
                        "filter_field or name. The frontend will leave the "
                        "matching form input disabled, FormData will drop "
                        "the key, and the tab will render with a spurious "
                        "'*' on first load."
                    ),
                    hint=(
                        "Use the SBAdminField's effective filter_field as "
                        "the key. If the field has an explicit "
                        "filter_field=X, use X; otherwise use the field's "
                        "name. Custom widgets that hardcode their Q(...) "
                        "should usually NOT set filter_field at all."
                    ),
                    obj=admin.__class__,
                    id="sbadmin.W002",
                )
            )
    return warnings


def check_ordering_columns_for_admin(admin):
    """Per-admin implementation of ``sbadmin.W003``. Exposed for unit tests."""
    warnings = []
    ordering = getattr(admin, "ordering", None) or ()
    if not ordering:
        return warnings
    known_names: set[str] = set()
    for entry in getattr(admin, "sbadmin_list_display", None) or ():
        if isinstance(entry, SBAdminField):
            if entry.name:
                known_names.add(entry.name)
        elif isinstance(entry, str):
            known_names.add(entry)

    for raw in ordering:
        if not isinstance(raw, str):
            continue
        field = raw.lstrip("-")
        if "__" in field or "?" in field:
            # Related lookup or random ordering; Tabulator can't represent it
            # as a column field anyway. Out of scope for this check.
            continue
        if field in known_names:
            continue
        warnings.append(
            Warning(
                (
                    f"{admin.__class__.__name__}: ordering references "
                    f"{field!r} which has no matching SBAdminField (or "
                    "plain field) in sbadmin_list_display. Tabulator "
                    "drops it from tableInitialSort, the live sort differs "
                    "from initial, and the view tab renders with a "
                    "spurious '*'."
                ),
                hint=(
                    "Add a hidden column for the sort target: "
                    f"SBAdminField(name={field!r}, list_visible=False, "
                    "filter_disabled=True)."
                ),
                obj=admin.__class__,
                id="sbadmin.W003",
            )
        )
    return warnings


_PER_ADMIN_CHECKS = (
    check_duplicate_filter_field_for_admin,
    check_view_config_filter_keys_for_admin,
    check_ordering_columns_for_admin,
)


@register(Tags.admin)
def check_sbadmin_list_view_config(app_configs, **kwargs):
    """Aggregated Django system check for all SBAdmin admins.

    Iterates the per-admin check helpers above. Split this way so each helper
    is directly unit-testable without monkey-patching ``sb_admin_site``.
    """
    warnings = []
    for admin in _admin_targets():
        for check in _PER_ADMIN_CHECKS:
            warnings.extend(check(admin))
    return warnings
