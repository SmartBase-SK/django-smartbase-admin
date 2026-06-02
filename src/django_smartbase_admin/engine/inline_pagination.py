from __future__ import annotations

from typing import Any

from django.contrib.admin import StackedInline, TabularInline
from django.contrib.admin.views.main import ChangeList
from django.contrib.contenttypes.admin import GenericTabularInline
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest

SBADMIN_INLINE_PREFIX_HEADER = "X-SBAdmin-Inline-Prefix"


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
    htmx_enabled = True

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

    def mount_paginator(self, page_num: int | None = None) -> None:
        assert self.queryset is not None and self.request is not None

        page_num = page_num or self.get_page_num()
        self.paginator = Paginator(self.queryset, self.per_page)
        self.page = self.get_page(self.paginator, page_num)
        self.cl = InlineChangeList(self.request, page_num, self.paginator)

    def mount_queryset(self) -> None:
        if self.cl.show_all:
            self._queryset = self.queryset
            return

        self._queryset = self.page.object_list


class InlinePaginated:
    pagination_key = "page"
    formset_prefix = None
    template = "sb_admin/inlines/table_inline_paginated.html"
    per_page = 20
    extra = 0
    htmx_enabled = True

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
        return PaginationFormSet


class StackedInlinePaginated(InlinePaginated, StackedInline):
    template = "sb_admin/inlines/stacked_inline.html"


class TabularInlinePaginated(InlinePaginated, TabularInline):
    pass


class GenericTabularInlinePaginated(InlinePaginated, GenericTabularInline):
    pass
