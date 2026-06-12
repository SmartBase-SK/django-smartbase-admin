from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.admin import StackedInline, TabularInline
from django.contrib.admin.views.main import ChangeList
from django.contrib.contenttypes.admin import GenericTabularInline
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import CharField, EmailField, Q, QuerySet, SlugField, TextField
from django.http import HttpRequest

from django_smartbase_admin.engine.const import ROW_CLASS_FIELD

SBADMIN_INLINE_PREFIX_HEADER = "X-SBAdmin-Inline-Prefix"
INLINE_SEARCH_TEXT_FIELD_TYPES = (CharField, TextField, EmailField, SlugField)
PG_UNACCENT_EXT_CACHE: dict[str, bool] = {}


def get_model_text_field_names(model) -> list[str]:
    return [
        field.name
        for field in model._meta.fields
        if isinstance(field, INLINE_SEARCH_TEXT_FIELD_TYPES)
    ]


def resolve_search_lookups_for_model_field(model, field_name: str) -> list[str]:
    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return []

    if isinstance(field, INLINE_SEARCH_TEXT_FIELD_TYPES):
        return [field_name]

    related_model = getattr(field, "related_model", None)
    if related_model is None:
        return []

    return [
        f"{field_name}__{related_field_name}"
        for related_field_name in get_model_text_field_names(related_model)
    ]


def resolve_search_fields_from_inline_table(inline, request, parent_obj=None) -> list[str]:
    inline_field_names = [
        str(name)
        for name in (inline.get_fields(request, parent_obj) or [])
        if name and name != ROW_CLASS_FIELD
    ]
    model = getattr(inline, "model", None)
    if model is None:
        return []

    lookups: list[str] = []
    seen: set[str] = set()
    for field_name in inline_field_names:
        for lookup in resolve_search_lookups_for_model_field(model, field_name):
            if lookup in seen:
                continue
            seen.add(lookup)
            lookups.append(lookup)
    return lookups


def get_inline_partial_prefix(request: HttpRequest) -> str | None:
    if request.headers.get("HX-Request") != "true":
        return None
    return request.headers.get(SBADMIN_INLINE_PREFIX_HEADER)


def get_inline_admin_formset_by_prefix(context: dict, inline_prefix: str):
    for inline_admin_formset in context.get("inline_admin_formsets", ()):
        if inline_admin_formset.formset.prefix == inline_prefix:
            return inline_admin_formset
    return None


class InlineChangeList:
    can_show_all = True
    multi_page = True
    get_query_string = ChangeList.__dict__["get_query_string"]

    def __init__(self, request: HttpRequest, page_num: int, paginator: Paginator):
        self.show_all = "all" in request.GET
        self.page_num = page_num
        self.paginator = paginator
        self.result_count = paginator.count
        self.params = dict(request.GET.items())


class PaginationFormSetBase:
    queryset: QuerySet | None = None
    request: HttpRequest | None = None
    per_page = 20
    pagination_key = "page"
    search_key_suffix = "-q"
    htmx_enabled = True
    inline_search_enabled = True

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.mount_paginator()
        self.mount_queryset()

    def get_page_num(self) -> int:
        assert self.request is not None

        for value in (
            self.request.GET.get(self.pagination_key),
            self.request.POST.get(f"_paginator-plus-{self.prefix}"),
        ):
            if value and value.isnumeric():
                page_num = int(value)
                if page_num > 0:
                    return page_num

        return 1

    def get_page(self, paginator: Paginator, page_num: int):
        if 1 <= page_num <= paginator.num_pages:
            return paginator.page(page_num)

        return paginator.page(1)

    def get_search_key(self) -> str:
        return f"{self.prefix}{self.search_key_suffix}"

    def get_search_term(self) -> str:
        assert self.request is not None
        search_key = self.get_search_key()
        raw_value = self.request.GET.get(search_key)
        if raw_value is None:
            raw_value = self.request.POST.get(search_key)
        return (raw_value or "").strip()

    def get_search_fields(self) -> list[str]:
        if not self.inline_search_enabled:
            return []
        inline_admin = getattr(self, "inline_admin", None)
        if inline_admin is not None:
            parent_obj = getattr(self, "instance", None)
            lookups = inline_admin.get_inline_search_fields(
                self.request, parent_obj
            )
            if lookups:
                return lookups
        return get_model_text_field_names(self.model)

    @staticmethod
    def _postgres_unaccent_extension_available() -> bool:
        if connection.vendor != "postgresql":
            return False
        if "django.contrib.postgres" not in settings.INSTALLED_APPS:
            return False
        alias = connection.alias
        cached = PG_UNACCENT_EXT_CACHE.get(alias)
        if cached is not None:
            return cached
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = %s LIMIT 1",
                    ["unaccent"],
                )
                available = bool(cursor.fetchone())
        except Exception:
            available = False
        PG_UNACCENT_EXT_CACHE[alias] = available
        return available

    def get_search_lookup(self, field_name: str, prefix: str = "") -> str:
        if prefix == "^":
            return f"{field_name}__istartswith"
        if prefix == "=":
            return f"{field_name}__iexact"
        if prefix == "@":
            return f"{field_name}__search"
        if self._postgres_unaccent_extension_available():
            return f"{field_name}__unaccent__icontains"
        return f"{field_name}__icontains"

    def filter_queryset_by_search(self, queryset: QuerySet) -> QuerySet:
        self.search_term = self.get_search_term()
        if not self.search_term:
            return queryset
        search_fields = self.get_search_fields()
        if not search_fields:
            return queryset

        search_filters = Q()
        needs_distinct = False
        for raw_field in search_fields:
            if not raw_field:
                continue
            prefix = raw_field[0] if raw_field[0] in "^=@" else ""
            field_name = raw_field[1:] if prefix else raw_field
            if not field_name:
                continue
            lookup = self.get_search_lookup(field_name, prefix=prefix)
            search_filters |= Q(**{lookup: self.search_term})
            needs_distinct = needs_distinct or "__" in field_name

        if not search_filters.children:
            return queryset

        filtered_queryset = queryset.filter(search_filters)
        if needs_distinct:
            filtered_queryset = filtered_queryset.distinct()
        return filtered_queryset

    def mount_paginator(self, page_num: int | None = None) -> None:
        assert self.queryset is not None and self.request is not None

        page_num = page_num or self.get_page_num()
        self.filtered_queryset = self.filter_queryset_by_search(self.queryset)
        self.paginator = Paginator(self.filtered_queryset, self.per_page)
        self.page = self.get_page(self.paginator, page_num)
        self.cl = InlineChangeList(self.request, page_num, self.paginator)

    def mount_queryset(self) -> None:
        if self.cl.show_all:
            self._queryset = self.filtered_queryset
            return

        self._queryset = self.page.object_list


class InlinePaginated:
    pagination_key = "page"
    formset_prefix = None
    template = "sb_admin/inlines/table_inline_paginated.html"
    per_page = 20
    extra = 0
    search_key_suffix = "-q"
    htmx_enabled = True
    inline_search_enabled = True
    inline_search_fields = None

    def get_inline_search_fields(self, request, obj=None) -> list[str]:
        if self.inline_search_fields:
            return list(self.inline_search_fields)
        return resolve_search_fields_from_inline_table(self, request, obj)

    def get_formset(self, request, obj=None, **kwargs):
        formset_class = super().get_formset(request, obj, **kwargs)
        formset_prefix = self.formset_prefix

        class PaginationFormSet(PaginationFormSetBase, formset_class):
            pagination_key = self.pagination_key

            @classmethod
            def get_default_prefix(cls):
                if formset_prefix:
                    return formset_prefix
                return super().get_default_prefix()

        PaginationFormSet.request = request
        PaginationFormSet.per_page = self.per_page
        PaginationFormSet.htmx_enabled = self.htmx_enabled
        PaginationFormSet.search_key_suffix = self.search_key_suffix
        PaginationFormSet.inline_search_enabled = self.inline_search_enabled
        PaginationFormSet.inline_admin = self
        return PaginationFormSet


class StackedInlinePaginated(InlinePaginated, StackedInline):
    template = "sb_admin/inlines/stacked_inline.html"


class TabularInlinePaginated(InlinePaginated, TabularInline):
    pass


class GenericTabularInlinePaginated(InlinePaginated, GenericTabularInline):
    pass
