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
        "parent_field_guarantees_root": False,    # optional, default False
    }

Why the pipeline looks the way it does:

* Pagination has to be on **parent groups** (so "1 page = N roots +
  their children"), not raw rows. The grouping query unions root pks
  with matching child parent pks, then lets SQL's normal ``UNION``
  distinct step collapse duplicates.

* The page slice knows *which parent groups* are visible but not the
  rows themselves. ``modify_base_queryset`` stashes the **unfiltered**
  base qs so ``modify_raw_data`` can hydrate rows (parents always
  resolve, even when the filter excluded them but matched a child).
  Two filter shapes, same downstream tree-assembly loop:

    - ``only_show_filtered_children=True``:
      parent rows unioned with matching filtered child rows.
    - ``only_show_filtered_children=False``:
      parent rows unioned with all direct reports of each visible
      root.

Only one level is rendered. Grandchildren and deeper rows are
dropped at the parent-group step (see ``_build_parent_group_qs``) so they
don't surface as bogus single-row top-level groups unless
``parent_field_guarantees_root=True`` opts out of that guard.
"""

from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import F, OuterRef, Subquery

from django_smartbase_admin.plugins.base import SBAdminPlugin

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

    from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
    from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView


CHILDREN_FIELD = "_children"
PARENT_REAL_ID = "parent_real_id"
CHILDREN_IDS = "children_ids"
LAST_CHILD_FIELD = "_sbadmin_tree_last_child"

_KNOWN_KEYS = {
    "parent_field",
    "element_column",
    "start_expanded",
    "only_show_filtered_children",
    "parent_field_guarantees_root",
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
        """Tell Tabulator to render returned rows as a one-level tree."""
        nested = resolve_nested(view, request)
        if nested is None:
            return definition
        element_column = _resolve_element_column(view, request, nested)
        options: dict[str, Any] = {
            "dataTree": True,
            "dataTreeChildField": CHILDREN_FIELD,
            "dataTreeStartExpanded": nested.get("start_expanded", False),
            "sbadminTreeLastChildField": LAST_CHILD_FIELD,
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
        """Remember the unfiltered row queryset used later for hydration."""
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # parent_field has to be in the values list so
        # ``modify_raw_data`` can map each row back to its parent.
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
        """Count parent groups, not raw package/category rows."""
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # Count needs distinct parent groups only.
        return cls._build_parent_group_qs(
            action, qs, nested, include_sort_columns=False
        )

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
        """Return the parent-group page and stash child ids for hydration."""
        nested = resolve_nested(action.view, request)
        if nested is None:
            return qs
        # Stash caller ordering so ``modify_raw_data`` can apply it
        # to child rows too — otherwise groups sort correctly but
        # children land in whatever order the hydration query returned.
        store = cls.get_request_data_plugin_store(request)
        parent_field: str = nested["parent_field"]
        pk_name = action.get_pk_field().name

        # This queryset keeps the active filters/search, so final
        # hydration can include only children that actually matched.
        child_qs = qs.filter(**{f"{parent_field}__isnull": False})
        if not nested.get("parent_field_guarantees_root", False):
            child_qs = child_qs.filter(
                **{f"{parent_field}__in": cls._visible_parent_ids(action, nested)}
            )
        store["filtered_child_ids_qs"] = child_qs.order_by().values(pk_name)
        store["order_by"] = [
            expr for expr in qs.query.order_by if isinstance(expr, str)
        ]
        return cls._build_parent_group_qs(action, qs, nested)

    @classmethod
    def modify_raw_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Replace page-group rows with raw hydrated parents and children."""
        nested = resolve_nested(action.view, request)
        if nested is None:
            return data
        pk_name = action.get_pk_field().name
        parent_field: str = nested["parent_field"]
        only_filtered = nested.get("only_show_filtered_children", True)

        parent_ids = [
            root_id
            for group in data
            if (root_id := group.get(PARENT_REAL_ID)) is not None
        ]
        store = cls.get_request_data_plugin_store(request)
        store["parent_ids"] = parent_ids
        if not parent_ids:
            return []

        # Hydrate parents + children in a single query against the
        # unfiltered base qs from ``modify_base_queryset``. Parents
        # excluded by the list filter still resolve here, which is
        # why the base qs is kept unfiltered.
        base_qs = store.get("base_qs")
        if base_qs is None:
            return data

        # Build both sides from ``base_qs`` so UNION ALL has an
        # identical selected-column shape on every supported backend.
        parent_qs = base_qs.filter(**{f"{pk_name}__in": parent_ids}).order_by()
        if only_filtered:
            filtered_child_ids_qs = store.get("filtered_child_ids_qs")
            if filtered_child_ids_qs is None:
                child_qs = base_qs.none()
            else:
                child_qs = base_qs.filter(
                    **{f"{pk_name}__in": Subquery(filtered_child_ids_qs)}
                )
        else:
            child_qs = base_qs
        child_qs = child_qs.filter(**{f"{parent_field}__in": parent_ids}).order_by()
        hydrated = parent_qs.union(child_qs, all=True)
        # Apply the caller's sort to children too so each parent's
        # ``_children`` list follows the same order the user chose
        # at the top level. Groups themselves are already sorted by
        # the page slice; this only affects sibling order under a
        # parent.
        order_by = store.get("order_by") or []
        if order_by:
            hydrated = hydrated.order_by(*order_by)
        return list(hydrated)

    @classmethod
    def modify_final_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Assemble finalized parent and child rows into ``_children``."""
        nested = resolve_nested(action.view, request)
        if nested is None:
            return data
        pk_name = action.get_pk_field().name
        parent_field: str = nested["parent_field"]
        store = cls.get_request_data_plugin_store(request)
        parent_ids = store.get("parent_ids")
        if parent_ids is None:
            return data
        if not parent_ids:
            return []

        # Group direct children by their root parent id; grandchildren
        # are already excluded unless the admin opted out via config.
        parent_id_set = set(parent_ids)
        by_id = {row[pk_name]: row for row in data}
        children_by_parent: dict[Any, list[dict[str, Any]]] = {}
        for row in data:
            pid = row.get(parent_field)
            if pid is None or pid == row.get(pk_name) or pid not in parent_id_set:
                continue
            children_by_parent.setdefault(pid, []).append(row)

        result: list[dict[str, Any]] = []
        for root_id in parent_ids:
            root_row = by_id.get(root_id)
            if root_row is None:
                continue
            children = children_by_parent.get(root_id)
            if children:
                children[-1][LAST_CHILD_FIELD] = True
                action._strip_to_visible_keys(children)
                root_row[CHILDREN_FIELD] = children
            else:
                root_row.pop(CHILDREN_FIELD, None)
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
            row.pop(LAST_CHILD_FIELD, None)
            if children:
                children[-1].pop(LAST_CHILD_FIELD, None)
            flattened.append(row)
            flattened.extend(children)
        return flattened

    @classmethod
    def _build_parent_group_qs(
        cls,
        action: "SBAdminListAction",
        filtered_qs: "QuerySet",
        nested: dict,
        include_sort_columns: bool = True,
    ) -> "QuerySet":
        """Return visible parent group ids from root and child matches.

        The caller slices this queryset for pagination. ``UNION`` is
        deliberate: if both a parent and one of its children match the
        active filters, SQL de-duplicates that parent id before count
        and pagination run.
        """
        parent_field: str = nested["parent_field"]
        pk_name = action.get_pk_field().name

        # Capture caller ordering before we clear it; only simple
        # column strings are rewritable. Non-string expressions
        # (e.g. OrderBy objects) are dropped — in practice
        # get_order_by_from_request always returns strings.
        order_strings = [
            expr for expr in filtered_qs.query.order_by if isinstance(expr, str)
        ]

        parent_branch = (
            filtered_qs.filter(**{f"{parent_field}__isnull": True})
            .order_by()
            .annotate(**{PARENT_REAL_ID: F(pk_name)})
        )

        # Child matches page by their root parent id. The root guard is
        # the safe default; projects with enforced one-level nesting can
        # opt out with ``parent_field_guarantees_root=True``.
        child_branch = filtered_qs.filter(**{f"{parent_field}__isnull": False})
        if not nested.get("parent_field_guarantees_root", False):
            child_branch = child_branch.filter(
                **{f"{parent_field}__in": cls._visible_parent_ids(action, nested)}
            )
        child_branch = child_branch.order_by().annotate(
            **{PARENT_REAL_ID: F(parent_field)}
        )

        if not include_sort_columns:
            return parent_branch.values(PARENT_REAL_ID).union(
                child_branch.values(PARENT_REAL_ID)
            )

        column_fields_map = {column.field: column for column in action.column_fields}
        values = [PARENT_REAL_ID]
        new_order: list[str] = []
        for idx, expr in enumerate(order_strings):
            desc = expr.startswith("-")
            field = expr.lstrip("-+")
            alias = f"_nested_sort_{idx}"
            visible_field = column_fields_map.get(field)
            base_sort_qs = action.get_data_queryset(visible_fields=[]).order_by()
            is_direct_parent_sort = _is_direct_parent_sort_source(
                action.view.model, base_sort_qs, field
            )
            if is_direct_parent_sort:
                # Simple model/display fields can sort by the parent's
                # raw column without rebuilding the annotated list queryset.
                sort_parent_qs = base_sort_qs
                parent_branch = parent_branch.annotate(**{alias: F(field)})
                child_branch = child_branch.annotate(
                    **{
                        alias: Subquery(
                            sort_parent_qs.filter(pk=OuterRef(parent_field)).values(
                                field
                            )[:1]
                        )
                    }
                )
            else:
                # Complex annotations fall back to the list queryset so
                # custom SBAdminField annotations still sort correctly.
                sort_parent_qs = action.get_data_queryset(
                    visible_fields=[visible_field] if visible_field else []
                ).order_by()
                parent_branch = parent_branch.annotate(
                    **{
                        alias: Subquery(
                            sort_parent_qs.filter(pk=OuterRef(pk_name)).values(field)[
                                :1
                            ]
                        )
                    }
                )
                child_branch = child_branch.annotate(
                    **{
                        alias: Subquery(
                            sort_parent_qs.filter(pk=OuterRef(parent_field)).values(
                                field
                            )[:1]
                        )
                    }
                )
            values.append(alias)
            new_order.append(f"-{alias}" if desc else alias)
        return (
            parent_branch.values(*values)
            .union(child_branch.values(*values))
            .order_by(*new_order)
        )

    @classmethod
    def _visible_parent_ids(
        cls, action: "SBAdminListAction", nested: dict
    ) -> "QuerySet":
        """Parent ids allowed to own tree rows under current permissions."""
        parent_field: str = nested["parent_field"]
        pk_name = action.get_pk_field().name
        return (
            action.view.get_queryset(action.threadsafe_request)
            .filter(**{f"{parent_field}__isnull": True})
            .values(pk_name)
        )


def _is_direct_parent_sort_source(model, base_qs: "QuerySet", source: str) -> bool:
    if not isinstance(source, str):
        return False
    source = source.lstrip("-+")
    if source in base_qs.query.annotations:
        return True
    current_model = model
    parts = source.split("__")
    for part in parts:
        try:
            field = current_model._meta.get_field(part)
        except FieldDoesNotExist:
            return False
        current_model = getattr(field, "related_model", None)
        if current_model is None and part != parts[-1]:
            return False
    return True


def _validate(view, nested: dict) -> None:
    """Validate nested plugin config once per resolved view."""
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
