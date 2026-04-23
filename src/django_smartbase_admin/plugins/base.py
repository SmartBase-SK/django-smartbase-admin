"""Plugin protocol for SBAdmin list views.

Plugins are registered on :class:`SBAdminRoleConfiguration` via the
``plugins=[...]`` constructor argument. Subclasses override only the
hooks they care about and self-guard by inspecting admin config
(e.g. ``view.sbadmin_nested``) — returning the input unchanged when
the plugin doesn't apply.

Hook pipeline (in call order):

1. ``modify_tabulator_definition`` — Tabulator JSON sent to the client.
2. ``modify_count_queryset`` — the qs ``.count()`` runs on (e.g. group
   by parent id so pagination counts parent groups, not rows).
3. ``modify_base_queryset`` — unfiltered ``.values()``-applied qs;
   **store-only**. Reshaping here leaks into the visible page.
4. ``modify_data_queryset`` — unsliced, filtered, ordered qs; returned
   qs is sliced ``[from:to]`` by the caller.
5. ``modify_final_data`` — reshape the already-formatted row dicts
   (e.g. assemble ``_children`` trees from group metadata).
6. ``modify_xlsx_data`` — final pass before XLSX serialization, after
   all paged ``get_data`` chunks are concatenated (e.g. flatten a
   ``_children`` tree back into sibling rows the spreadsheet can render).

Hook contract:

* Hooks are ``classmethod`` — plugins are stateless.
* Every hook takes ``request`` + ``**kwargs`` so call sites stay
  backwards compatible.
* Plugins that need to re-enter ``build_final_data_{count_,}queryset``
  pass ``apply_plugins=False`` to avoid recursion.
* Cross-hook state goes through
  :meth:`SBAdminPlugin.get_request_data_plugin_store`; the action
  never writes into a plugin's slot.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

    from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
    from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView


#: Slot on ``request.request_data.additional_data``; each plugin
#: gets its own sub-dict keyed by ``cls.__name__`` so plugins don't
#: stomp on each other.
PLUGIN_DATA_KEY = "sbadmin_plugin_data"


class SBAdminPlugin:
    """Classmethod-only plugin base for list views.

    Plugins are stateless by contract — within a single request they
    share state across hooks via
    :meth:`get_request_data_plugin_store`. The action never writes
    into a plugin's slot; all queryset building and stashing is the
    plugin's own responsibility.
    """

    @classmethod
    def get_request_data_plugin_store(cls, request: "HttpRequest") -> dict[str, Any]:
        """Per-request, per-plugin-class scratch dict, keyed by
        ``cls.__name__`` so sibling plugins don't collide."""
        additional = request.request_data.additional_data
        store: dict[str, dict[str, Any]] = additional.setdefault(PLUGIN_DATA_KEY, {})
        return store.setdefault(cls.__name__, {})

    @classmethod
    def modify_base_queryset(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        qs: "QuerySet",
        values: list[str],
        **kwargs: Any,
    ) -> "QuerySet":
        """Observation hook — **store-only**. Any reshape here
        propagates into filter / search / order / slice and silently
        changes the visible page; return ``qs`` unchanged."""
        return qs

    @classmethod
    def modify_tabulator_definition(
        cls,
        view: "SBAdminBaseListView",
        request: "HttpRequest",
        definition: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return definition

    @classmethod
    def modify_count_queryset(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        qs: "QuerySet",
        **kwargs: Any,
    ) -> "QuerySet":
        """Reshape the qs ``.count()`` runs on (e.g. group by parent
        id so pagination counts parent groups, not rows)."""
        return qs

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
        """Reshape the unsliced, filtered, ordered data qs; caller
        slices ``[from:to]`` on the return value."""
        return qs

    @classmethod
    def modify_final_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Reshape rows **after** column formatters have run (e.g.
        assemble a ``_children`` tree from group metadata)."""
        return data

    @classmethod
    def modify_xlsx_data(
        cls,
        action: "SBAdminListAction",
        request: "HttpRequest",
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Final pass before XLSX serialization. Runs once on the
        concatenated rows from all paged ``get_data`` chunks — the
        right place to unbundle tree rows (``_children``) that the
        spreadsheet can't render nested."""
        return data
