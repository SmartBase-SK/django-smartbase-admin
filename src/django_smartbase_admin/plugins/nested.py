"""Tabulator nested (one-level) data plugin.

Admins opt in by declaring :attr:`sbadmin_nested` on the admin and
registering :class:`TabulatorNestedPlugin` on
``SBAdminRoleConfiguration.plugins``::

    plugins = [TabulatorNestedPlugin]

    sbadmin_nested = {
        "parent_field": "<self_fk_field>",        # required self-ref FK
        "element_column": "<tree_toggle_column>", # optional: column that shows the expand/collapse toggle
        "start_expanded": False,                  # optional
        "only_show_filtered_children": True,      # optional, default True
    }

Why the pipeline looks the way it does:

* Pagination has to be on **parent groups** (so "1 page = N roots +
  their children"), not raw rows. The grouping
  ``parent_real_id = COALESCE(parent_field, pk)`` collapses each
  child onto its parent's pk and lets roots (``parent_field IS
  NULL``) fall into their own group in one query — no subqueries,
  no two-phase counting. That's what ``modify_count_queryset`` /
  ``modify_data_queryset`` return.

* The page slice knows *which parent groups* are visible but not the
  rows themselves. ``modify_base_queryset`` stashes the **unfiltered**
  base qs so ``modify_final_data`` can hydrate rows (parents always
  resolve, even when the filter excluded them but matched a child).
  Two filter shapes, same downstream tree-assembly loop:

    - ``only_show_filtered_children=True``:
      ``pk__in=(parent_ids | filtered_child_ids)`` — only the
      children that matched the filter.
    - ``only_show_filtered_children=False``:
      ``Q(pk__in=parent_ids) | Q(parent_field__in=parent_ids)`` —
      all direct reports of each visible root.

Only one level is rendered. Grandchildren and deeper rows are
dropped at the grouping step (see ``_build_grouped_qs``) so they
don't surface as bogus single-row top-level groups via the
``COALESCE`` trick.
"""

from typing import TYPE_CHECKING, Any

from django.contrib.postgres.aggregates import ArrayAgg
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Case, F, Max, Q, When
from django.db.models.functions import Coalesce

from django_smartbase_admin.plugins.base import SBAdminPlugin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

    from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
    from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView


CHILDREN_FIELD = "_children"
PARENT_REAL_ID = "parent_real_id"
CHILDREN_IDS = "children_ids"

_KNOWN_KEYS = {
    "parent_field",
    "element_column",
    "start_expanded",
    "only_show_filtered_children",
}


def resolve_nested(view, request=None) -> dict | None:
    """Return the validated nested config dict, or ``None`` if disabled.

    Calls ``view.get_sbadmin_nested(request)`` if present, otherwise
    reads ``view.sbadmin_nested``. Validation raises on malformed input.
    """
    getter = getattr(view, "get_sbadmin_nested", None)
    if callable(getter):
        nested = getter(request)
    else:
        nested = getattr(view, "sbadmin_nested", None)
    if nested is None:
        return None
    _validate(view, nested)
    return nested


def _resolve_element_column(view, request, nested: dict) -> str | None:
    """Return the Tabulator field id for ``element_column`` (or the first
    visible column as a default)."""
    field_map = view.get_field_map(request)
    tabulator_fields: list[str] = []
    for display_name in view.get_list_display(request):
        field = field_map.get(display_name)
        if field and getattr(field, "list_visible", True):
            tabulator_fields.append(field.field)
    default_element_column = tabulator_fields[0] if tabulator_fields else None
    configured = nested.get("element_column")
    if not configured:
        return default_element_column
    field = field_map.get(configured)
    if field is not None:
        return field.field
    return configured


class TabulatorNestedPlugin(SBAdminPlugin):
    """DB-level group-by plugin for Tabulator ``dataTree`` rendering."""

    @classmethod
    def modify_tabulator_definition(
        cls,
        view: "SBAdminBaseListView",
        request: "HttpRequest",
        definition: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        nested = resolve_nested(view, request)
        if nested is None:
            return definition
        element_column = _resolve_element_column(view, request, nested)
        options: dict[str, Any] = {
            "dataTree": True,
            "dataTreeChildField": CHILDREN_FIELD,
            "dataTreeStartExpanded": nested.get("start_expanded", False),
        }
        if element_column:
            options["dataTreeElementColumn"] = element_column
        definition.setdefault("tabulatorOptions", {}).update(options)
        return definition

    @classmethod
    def modify_base_queryset(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        qs: "QuerySet",
        values: list[str],
        **kwargs: Any,
    ) -> "QuerySet":
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # parent_field has to be in the values list so
        # ``modify_final_data`` can map each row back to its parent.
        parent_field: str = nested["parent_field"]
        hydration_values = list(values)
        if parent_field not in hydration_values:
            hydration_values.append(parent_field)
        store = cls.get_request_data_plugin_store(request)
        store["base_qs"] = qs.values(*hydration_values)
        store["values"] = hydration_values
        return qs

    @classmethod
    def modify_count_queryset(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        qs: "QuerySet",
        **kwargs: Any,
    ) -> "QuerySet":
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # Count needs distinct parent groups only — skip the
        # ``ArrayAgg`` aggregation entirely.
        return cls._build_grouped_qs(action, qs, nested, include_children_ids=False)

    @classmethod
    def modify_data_queryset(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        qs: "QuerySet",
        page_num: int,
        page_size: int,
        **kwargs: Any,
    ) -> "QuerySet":
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # Stash caller ordering so ``modify_final_data`` can apply it
        # to child rows too — otherwise groups sort correctly but
        # children land in whatever order the hydration query returned.
        store = cls.get_request_data_plugin_store(request)
        store["order_by"] = [
            expr for expr in qs.query.order_by if isinstance(expr, str)
        ]
        return cls._build_grouped_qs(action, qs, nested)

    @classmethod
    def modify_final_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        nested = resolve_nested(action.view, request)
        if nested is None:
            return data
        pk_name = action.get_pk_field().name
        parent_field: str = nested["parent_field"]
        only_filtered = nested.get("only_show_filtered_children", True)

        parent_ids: set = set()
        filtered_child_ids: set = set()
        for group in data:
            root_id = group.get(PARENT_REAL_ID)
            if root_id is not None:
                parent_ids.add(root_id)
            for cid in group.get(CHILDREN_IDS) or ():
                if cid == root_id:
                    continue
                filtered_child_ids.add(cid)
        if not parent_ids:
            return []

        # Hydrate parents + children in a single query against the
        # unfiltered base qs from ``modify_base_queryset``. Parents
        # excluded by the list filter still resolve here, which is
        # why the base qs is kept unfiltered.
        store = cls.get_request_data_plugin_store(request)
        base_qs = store.get("base_qs")
        if base_qs is None:
            return data
        if only_filtered:
            row_filter = Q(**{f"{pk_name}__in": list(parent_ids | filtered_child_ids)})
        else:
            row_filter = Q(**{f"{pk_name}__in": list(parent_ids)}) | Q(
                **{f"{parent_field}__in": list(parent_ids)}
            )
        hydrated = base_qs.filter(row_filter)
        # Apply the caller's sort to children too so each parent's
        # ``_children`` list follows the same order the user chose
        # at the top level. Groups themselves are already sorted by
        # the page slice; this only affects sibling order under a
        # parent.
        order_by = store.get("order_by") or []
        if order_by:
            hydrated = hydrated.order_by(*order_by)
        rows = list(hydrated)
        action.process_final_data(rows)

        by_id = {row[pk_name]: row for row in rows}
        children_by_parent: dict[Any, list[dict[str, Any]]] = {}
        for row in rows:
            pid = row.get(parent_field)
            if pid is None or pid == row.get(pk_name) or pid not in parent_ids:
                continue
            children_by_parent.setdefault(pid, []).append(row)

        result: list[dict[str, Any]] = []
        for group in data:
            root_id = group.get(PARENT_REAL_ID)
            root_row = by_id.get(root_id)
            if root_row is None:
                continue
            root_row[CHILDREN_FIELD] = children_by_parent.get(root_id, [])
            result.append(root_row)
        return result

    @classmethod
    def modify_xlsx_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Flatten the ``_children`` tree back into sibling rows.

        XLSX columns are flat, so nested children disappear if left
        under ``_children``. Emit parent then its direct children in
        order — the caller's sort was already applied during
        hydration, so sibling order is preserved.
        """
        nested = resolve_nested(action.view, request)
        if nested is None:
            return data
        flattened: list[dict[str, Any]] = []
        for row in data:
            children = row.pop(CHILDREN_FIELD, None) or []
            flattened.append(row)
            flattened.extend(children)
        return flattened

    @classmethod
    def _build_grouped_qs(
        cls,
        action: "SBAdminListAction",
        filtered_qs: "QuerySet",
        nested: dict,
        include_children_ids: bool = True,
    ) -> "QuerySet":
        """Group ``filtered_qs`` by ``parent_real_id`` in one query.

        Trick: ``COALESCE(parent_field, pk)``. Roots
        (``parent_field IS NULL``) resolve to their own pk and form
        their own group naturally — no subquery needed to find
        "parents that matched".

        Only one level is supported. Rows are kept iff they are a
        root themselves or their parent is a visible root; anything
        deeper (grandchildren, ...) is dropped by that same filter,
        which also re-enforces ``restrict_queryset`` on the parent
        side of the FK (Django's FK JOIN doesn't invoke the parent's
        manager).

        Caller ordering is preserved but rewritten to aggregate-per-
        group: the sort columns are pulled from the **parent row**
        (``parent_field IS NULL``) via ``MAX(CASE WHEN ...)``. Left
        raw, Django's compiler auto-appends them to ``GROUP BY`` to
        keep the generated SQL valid, which splits every parent into
        one row per distinct child sort value and duplicates groups
        in both count and data queries.
        """
        parent_field: str = nested["parent_field"]
        pk_name = action.get_pk_field().name
        parent_real_id = Coalesce(F(parent_field), F(pk_name))

        # Pks allowed to act as parents in the tree: rows passing
        # ``restrict_queryset`` AND themselves roots. One subquery, two
        # jobs: drops grandchildren (their parent isn't a root so it
        # isn't in this set) and keeps ``restrict_queryset`` honored on
        # the parent side of the FK — otherwise a child whose parent
        # was filtered out leaks in as a phantom top-level group and
        # vanishes from the rendered page during hydration.
        visible_parent_ids = (
            action.view.get_queryset(action.threadsafe_request)
            .filter(**{f"{parent_field}__isnull": True})
            .values(pk_name)
        )

        # Capture caller ordering before we clear it; only simple
        # column strings are rewritable. Non-string expressions
        # (e.g. OrderBy objects) are dropped — in practice
        # get_order_by_from_request always returns strings.
        order_strings = [
            expr for expr in filtered_qs.query.order_by if isinstance(expr, str)
        ]

        grouped = (
            filtered_qs.filter(
                Q(**{f"{parent_field}__isnull": True})
                | Q(**{f"{parent_field}__in": visible_parent_ids})
            )
            # Drop caller ordering now — we re-apply it per group
            # below. Django's compiler auto-appends order-by columns
            # to ``GROUP BY`` on ``.values().annotate()`` queries,
            # which would split every parent into duplicate rows
            # (one per distinct child sort value).
            .order_by()
            .annotate(**{PARENT_REAL_ID: parent_real_id})
            .values(PARENT_REAL_ID)
        )

        if not include_children_ids:
            # Count path: distinct parent groups; ordering irrelevant.
            return grouped.distinct()

        grouped = grouped.annotate(**{CHILDREN_IDS: ArrayAgg(pk_name)})

        if not order_strings:
            return grouped

        # Re-apply caller ordering as per-group aggregates. Each
        # group contains exactly one parent row (``parent_field IS
        # NULL``), so ``MAX(CASE WHEN parent_row THEN col END)``
        # yields that parent's value — the group sorts by the
        # parent, not by any of its children.
        parent_row = Q(**{f"{parent_field}__isnull": True})
        sort_annotations: dict = {}
        new_order: list[str] = []
        for idx, expr in enumerate(order_strings):
            desc = expr.startswith("-")
            field = expr.lstrip("-+")
            alias = f"_nested_sort_{idx}"
            sort_annotations[alias] = Max(Case(When(parent_row, then=F(field))))
            new_order.append(f"-{alias}" if desc else alias)
        return grouped.annotate(**sort_annotations).order_by(*new_order)


def _validate(view, nested: dict) -> None:
    if not isinstance(nested, dict):
        raise ImproperlyConfigured(
            f"sbadmin_nested must be a dict, got {type(nested).__name__}"
        )
    if "parent_field" not in nested:
        raise ImproperlyConfigured("sbadmin_nested must contain a 'parent_field' key")
    unknown = set(nested) - _KNOWN_KEYS
    if unknown:
        raise ImproperlyConfigured(
            f"sbadmin_nested: unknown keys {sorted(unknown)}. "
            f"Known keys: {sorted(_KNOWN_KEYS)}"
        )
    name = nested["parent_field"]
    if not isinstance(name, str) or not name:
        raise ImproperlyConfigured(
            "sbadmin_nested['parent_field'] must be a non-empty field name"
        )
    model = getattr(view, "model", None)
    if model is None:
        return
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist as exc:
        raise ImproperlyConfigured(
            f"sbadmin_nested['parent_field']={name!r} does not exist on "
            f"{model.__name__}"
        ) from exc
    if not getattr(field, "is_relation", False):
        raise ImproperlyConfigured(
            f"sbadmin_nested['parent_field']={name!r} must be a ForeignKey"
        )
    related = getattr(field, "related_model", None)
    if related is not None and related is not model:
        # A proxy model is a different class object than the concrete
        # model its self-ref FK points at. Compare underlying concrete
        # models so proxies still validate as self-referential.
        concrete_view_model = getattr(
            getattr(model, "_meta", None), "concrete_model", model
        )
        concrete_related = getattr(
            getattr(related, "_meta", None), "concrete_model", related
        )
        if concrete_view_model is not concrete_related:
            raise ImproperlyConfigured(
                f"sbadmin_nested['parent_field']={name!r} must point at "
                f"the same model (self-referential FK)"
            )
