from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View

from django_smartbase_admin.services.media_picker import FilerMediaPickerService
from django_smartbase_admin.services.configuration import (
    SBAdminUserConfigurationService,
)
from django_smartbase_admin.templatetags.sb_paginated_inline import (
    build_tabulator_style_page_items,
)


class MediaPickerView(View):
    template_name = "sb_admin/media_picker/picker.html"
    embedded_template_name = "sb_admin/media_picker/iframe.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        return self.render_picker(request, request.GET)

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            parent_value = request.POST.get("folder")
            parent_id = int(parent_value) if parent_value else None
        except (TypeError, ValueError):
            return self.render_picker(
                request,
                request.POST,
                errors=[_("Invalid folder.")],
            )

        try:
            FilerMediaPickerService.create_folder(
                request,
                parent_id=parent_id,
                name=request.POST.get("name", ""),
            )
        except ValidationError as error:
            return self.render_picker(
                request,
                request.POST,
                errors=error.messages,
            )
        return self.render_picker(request, request.POST)

    def render_picker(
        self,
        request: HttpRequest,
        params: Mapping[str, Any],
        *,
        errors: list[str] | None = None,
    ) -> HttpResponse:
        page = FilerMediaPickerService.get_page(request, params)
        # django-filer's no-folder uploader resolves its destination from this key.
        request.session["filer_last_folder_id"] = (
            None if page.folder is None else page.folder.pk
        )
        context = FilerMediaPickerService.page_data(page)
        route = reverse("sb_admin:media_picker")
        picker_type = page.picker_type
        endpoint = self.build_url(
            route,
            picker_type=picker_type,
            is_public=page.is_public,
        )
        query = str(params.get("q", "")).strip()
        ordering = str(params.get("order_by", "-uploaded_at"))
        pagination_items = build_tabulator_style_page_items(
            current_page=page.pagination.number,
            max_page=page.pagination.paginator.num_pages,
        )
        for item in pagination_items:
            if item["kind"] == "page":
                item["url"] = self.pagination_url(
                    route,
                    context,
                    query,
                    ordering,
                    item["number"],
                    page.is_public,
                )
        context.update(
            {
                "endpoint": endpoint,
                "query": query,
                "ordering": ordering,
                "errors": errors or [],
                "folder_entries": [
                    {
                        **folder,
                        "url": self.build_url(
                            route,
                            picker_type=picker_type,
                            is_public=page.is_public,
                            folder=folder["id"],
                            order_by=ordering,
                        ),
                    }
                    for folder in context["folders"]
                ],
                "breadcrumb_entries": [
                    {
                        **folder,
                        "url": self.build_url(
                            route,
                            picker_type=picker_type,
                            is_public=page.is_public,
                            folder=folder["id"],
                            order_by=ordering,
                        ),
                    }
                    for folder in context["breadcrumbs"]
                ],
                "root_url": self.build_url(
                    route,
                    picker_type=picker_type,
                    is_public=page.is_public,
                    order_by=ordering,
                ),
                "pagination_items": pagination_items,
                "previous_url": self.pagination_url(
                    route,
                    context,
                    query,
                    ordering,
                    page.pagination.number - 1,
                    page.is_public,
                ),
                "next_url": self.pagination_url(
                    route,
                    context,
                    query,
                    ordering,
                    page.pagination.number + 1,
                    page.is_public,
                ),
            }
        )
        embedded = request.method == "GET" and params.get("embedded") == "1"
        if embedded:
            context.update(
                {
                    "request_id": str(params.get("request_id", "")),
                    "selected_item": FilerMediaPickerService.selected_item_data(
                        request,
                        picker_type,
                        params.get("selected_id"),
                        is_public=page.is_public,
                    ),
                    "user_config": SBAdminUserConfigurationService.get_user_config(
                        request
                    ),
                }
            )
        template_name = self.embedded_template_name if embedded else self.template_name
        return render(request, template_name, context)

    @staticmethod
    def build_url(endpoint: str, **params: Any) -> str:
        clean_params = {
            key: value for key, value in params.items() if value not in (None, "")
        }
        return f"{endpoint}?{urlencode(clean_params)}" if clean_params else endpoint

    @classmethod
    def pagination_url(
        cls,
        endpoint: str,
        context: dict[str, Any],
        query: str,
        ordering: str,
        page: int,
        is_public: bool | None = None,
    ) -> str:
        folder = context["folder"]
        return cls.build_url(
            endpoint,
            picker_type=context["picker_type"],
            is_public=is_public,
            folder=None if folder is None else folder["id"],
            q=query,
            order_by=ordering,
            page=page,
        )
