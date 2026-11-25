from __future__ import annotations

import logging
import unicodedata
from dataclasses import asdict, dataclass, field

from django.db.models import Case, IntegerField, Q, Value, When
from django.utils.text import smart_split, unescape_string_literal
from django.utils.translation import gettext as _

from django_smartbase_admin.engine.const import (
    FILTER_DATA_NAME,
    TABLE_PARAMS_FULL_TEXT_SEARCH,
)

logger = logging.getLogger(__name__)

QUICK_SEARCH_MIN_LENGTH = 3
QUICK_SEARCH_MAX_LENGTH = 200
QUICK_SEARCH_ACTIONS_LIMIT = 5
QUICK_SEARCH_PAGES_LIMIT = 8
QUICK_SEARCH_RANK = "_sbadmin_quick_search_rank"
DEFAULT_ADD_ICON = "Add-one"
DEFAULT_PAGE_ICON = "Application-menu"
DEFAULT_RECORD_ICON = "Box"


@dataclass
class QuickSearchItem:
    title: str
    url: str
    description: str = ""
    icon: str = ""


@dataclass
class QuickSearchSection:
    key: str
    title: str
    items: list[QuickSearchItem] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "title": str(self.title),
            "items": [asdict(item) for item in self.items],
        }


def normalize_text(value) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.casefold()


def search_terms(term: str) -> list[str]:
    terms = []
    for bit in smart_split(term):
        if bit[:1] in ('"', "'") and bit[0] == bit[-1] and len(bit) > 1:
            bit = unescape_string_literal(bit)
        if bit.strip():
            terms.append(bit.strip())
    return terms


def text_rank(text: str, terms: list[str]) -> int | None:
    haystack = normalize_text(text)
    needles = [normalize_text(term) for term in terms]
    if not all(needle in haystack for needle in needles):
        return None
    phrase = " ".join(needles)
    if haystack == phrase:
        return 0
    if haystack.startswith(phrase):
        return 1
    return 2


class SBAdminQuickSearchMixin:
    """Record search in the quick search dialog (Ctrl/Cmd + K).

    By default the admin's ``search_fields`` are used, the same full-text
    search as in its list. ``sbadmin_quick_search_fields`` (ORM lookups with
    the ``^``, ``=`` and ``@`` prefixes) replaces them with a lighter query
    ranked by its first field: exact match, then prefix match.
    ``sbadmin_quick_search = False`` leaves the admin out.
    """

    sbadmin_quick_search: bool | None = None
    sbadmin_quick_search_fields: list[str] | tuple[str, ...] | None = None
    sbadmin_quick_search_limit: int = 5
    sbadmin_quick_search_icon: str | None = None

    def get_quick_search_fields(self, request) -> list[str]:
        return list(self.sbadmin_quick_search_fields or [])

    def uses_list_search_for_quick_search(self, request) -> bool:
        if self.get_quick_search_fields(request):
            return False
        if self.sbadmin_quick_search is None:
            configuration = getattr(
                getattr(request, "request_data", None), "configuration", None
            )
            if not getattr(configuration, "quick_search_use_search_fields", False):
                return False
        return bool(self.get_search_fields(request))

    def has_quick_search(self, request) -> bool:
        if self.sbadmin_quick_search is False:
            return False
        searchable = bool(
            self.get_quick_search_fields(request)
        ) or self.uses_list_search_for_quick_search(request)
        return searchable and bool(self.has_view_permission(request))

    def get_quick_search_section_title(self, request) -> str | None:
        return None

    def get_quick_search_icon(self, request) -> str:
        return self.sbadmin_quick_search_icon or DEFAULT_RECORD_ICON

    def _quick_search_lookup(self, request, field_name: str) -> str:
        prefix = field_name[0] if field_name[:1] in ("^", "=", "@") else ""
        raw_field_name = field_name[1:] if prefix else field_name
        return self.get_search_lookup(request, raw_field_name, prefix)

    def get_quick_search_list_queryset(self, request, term: str):
        list_action = self.sbadmin_list_action_class(
            self,
            request,
            all_params={
                self.get_id(): {FILTER_DATA_NAME: {TABLE_PARAMS_FULL_TEXT_SEARCH: term}}
            },
        )
        matching = list_action.build_final_data_count_queryset(apply_plugins=False)
        queryset = self.get_queryset(request).filter(pk__in=matching.values("pk"))
        ordering = list(queryset.query.order_by) or list(
            self.model._meta.ordering or []
        )
        return queryset.order_by(*ordering, "pk")

    def get_quick_search_queryset(self, request, term: str):
        fields = self.get_quick_search_fields(request)
        if not fields:
            return self.get_quick_search_list_queryset(request, term)
        queryset = self.get_queryset(request)
        for bit in search_terms(term):
            queryset = queryset.filter(
                Q.create(
                    [
                        (self._quick_search_lookup(request, name), bit)
                        for name in fields
                    ],
                    connector=Q.OR,
                )
            )
        rank_field = fields[0].lstrip("^=@")
        unaccent = "__unaccent" if self._postgres_unaccent_extension_available() else ""
        ordering = list(queryset.query.order_by) or list(
            self.model._meta.ordering or []
        )
        return queryset.annotate(
            **{
                QUICK_SEARCH_RANK: Case(
                    When(**{f"{rank_field}{unaccent}__iexact": term}, then=Value(0)),
                    When(
                        **{f"{rank_field}{unaccent}__istartswith": term}, then=Value(1)
                    ),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            }
        ).order_by(QUICK_SEARCH_RANK, *ordering, "pk")

    def get_quick_search_title(self, request, obj) -> str:
        return str(obj)

    def get_quick_search_description(self, request, obj) -> str:
        return ""

    def get_quick_search_url(self, request, obj) -> str:
        return self.get_detail_url(obj.pk)

    def get_quick_search_items(self, request, term: str) -> list[QuickSearchItem]:
        limit = self.sbadmin_quick_search_limit
        icon = self.get_quick_search_icon(request)
        items, seen = [], set()
        for obj in self.get_quick_search_queryset(request, term)[: limit * 3]:
            if obj.pk in seen:
                continue
            seen.add(obj.pk)
            items.append(
                QuickSearchItem(
                    title=str(self.get_quick_search_title(request, obj)),
                    description=str(self.get_quick_search_description(request, obj)),
                    url=self.get_quick_search_url(request, obj),
                    icon=icon,
                )
            )
            if len(items) >= limit:
                break
        return items


@dataclass
class _MenuEntry:
    label: str
    url: str
    icon: str
    path: list[str]
    view: object | None

    @property
    def breadcrumb(self) -> str:
        return " / ".join([*self.path, self.label])


class QuickSearchService:
    def __init__(self, request):
        self.request = request
        self.request_data = request.request_data
        self.configuration = self.request_data.configuration

    def menu_entries(self) -> list[_MenuEntry]:
        view_map = self.configuration.view_map
        entries = []

        def walk(items, path, parent_icon):
            for item in items:
                icon = item.get("get_icon") or parent_icon or ""
                label = str(item.get("get_label") or "")
                if item.get("get_url"):
                    entries.append(
                        _MenuEntry(
                            label=label,
                            url=item["get_url"],
                            icon=icon,
                            path=path,
                            view=view_map.get(item.get("get_view_id")),
                        )
                    )
                walk(item.get("sub_items") or [], [*path, label], icon)

        walk(self.request_data.menu_items or [], [], "")
        return entries

    def add_actions(
        self, entries: list[_MenuEntry]
    ) -> list[tuple[str, str, _MenuEntry]]:
        actions, seen = [], set()
        for entry in entries:
            view = entry.view
            if view is None or id(view) in seen:
                continue
            get_new_url = getattr(view, "get_new_url", None)
            if not callable(get_new_url) or not getattr(view, "model", None):
                continue
            seen.add(id(view))
            if not view.has_add_permission(self.request):
                continue
            url = get_new_url(self.request)
            if not url:
                continue
            add_label = view.get_add_label(self.request, None)
            title = (
                f"{_('Add')} {add_label}"
                if add_label
                else f"{_('Add')}: {view.model._meta.verbose_name}"
            )
            actions.append((title, url, entry))
        return actions

    def search_actions(self, terms, entries) -> list[QuickSearchItem]:
        ranked = []
        for title, url, entry in self.add_actions(entries):
            rank = text_rank(f"{title} {entry.breadcrumb}", terms) if terms else 2
            if rank is not None:
                ranked.append(
                    (
                        rank,
                        title,
                        QuickSearchItem(
                            title=title,
                            url=url,
                            description=entry.breadcrumb,
                            icon=DEFAULT_ADD_ICON,
                        ),
                    )
                )
        ranked.sort(key=lambda row: (row[0], normalize_text(row[1])))
        return [item for _rank, _title, item in ranked[:QUICK_SEARCH_ACTIONS_LIMIT]]

    def search_pages(self, terms, entries) -> list[QuickSearchItem]:
        ranked = []
        for entry in entries:
            rank = text_rank(entry.breadcrumb, terms) if terms else 2
            if rank is None:
                continue
            label_rank = text_rank(entry.label, terms) if terms else 2
            ranked.append(
                (
                    min(rank, 2 if label_rank is None else label_rank),
                    entry,
                )
            )
        ranked.sort(key=lambda row: row[0])
        return [
            QuickSearchItem(
                title=entry.label,
                url=entry.url,
                description=" / ".join(entry.path),
                icon=entry.icon or DEFAULT_PAGE_ICON,
            )
            for _rank, entry in ranked[:QUICK_SEARCH_PAGES_LIMIT]
        ]

    def record_views(self, entries) -> list:
        views, seen = [], set()
        for entry in entries:
            view = entry.view
            if view is None or id(view) in seen:
                continue
            seen.add(id(view))
            has_quick_search = getattr(view, "has_quick_search", None)
            if callable(has_quick_search) and has_quick_search(self.request):
                views.append((view, entry))
        return views

    def search_records(self, term, entries) -> list[QuickSearchSection]:
        sections = []
        for view, entry in self.record_views(entries):
            try:
                items = view.get_quick_search_items(self.request, term)
            except Exception:
                logger.exception("Quick search failed in %s", view.get_id())
                continue
            if items:
                sections.append(
                    QuickSearchSection(
                        key=f"records:{view.get_id()}",
                        title=view.get_quick_search_section_title(self.request)
                        or entry.label
                        or view.get_menu_label(),
                        items=items,
                    )
                )
        return sections

    def search(self, term: str) -> list[dict]:
        term = (term or "").strip()[:QUICK_SEARCH_MAX_LENGTH]
        terms = search_terms(term)
        entries = self.menu_entries()
        sections = [
            QuickSearchSection(
                key="actions",
                title=_("Quick actions"),
                items=self.search_actions(terms, entries),
            ),
            QuickSearchSection(
                key="pages",
                title=_("Pages"),
                items=self.search_pages(terms, entries),
            ),
        ]
        if len(term) >= QUICK_SEARCH_MIN_LENGTH:
            sections.extend(self.search_records(term, entries))
        return [section.as_dict() for section in sections if section.items]
