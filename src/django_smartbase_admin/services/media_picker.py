from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
from django.db import IntegrityError, models, transaction
from django.db.models import Case, When
from django.db.models.functions import Coalesce, Lower
from django.http import Http404, HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from filer import settings as filer_settings
from filer.cache import clear_folder_permission_cache
from filer.models import Folder, FolderPermission
from filer.utils.loader import load_model

from django_smartbase_admin.services.views import SBAdminViewService

MEDIA_PICKER_TYPE_FILE = "file"
MEDIA_PICKER_TYPE_IMAGE = "image"
MEDIA_PICKER_TYPES = {MEDIA_PICKER_TYPE_FILE, MEDIA_PICKER_TYPE_IMAGE}
MEDIA_PICKER_PAGE_SIZE = 100
FILER_PERMISSIONS_ALL = "All"
MEDIA_PICKER_ORDERING = {
    "-uploaded_at": ("-uploaded_at", "-pk"),
    "uploaded_at": ("uploaded_at", "pk"),
}


@dataclass(frozen=True, slots=True)
class MediaPickerPage:
    picker_type: str
    is_public: bool | None
    folder: Folder | None
    breadcrumbs: tuple[Folder, ...]
    folders: tuple[Folder, ...]
    items: tuple[Any, ...]
    pagination: Page
    can_upload: bool
    can_create_folder: bool
    upload_url: str | None


class FilerMediaPickerService:
    @classmethod
    def get_page(
        cls,
        request: HttpRequest,
        params: Mapping[str, Any] | None = None,
    ) -> MediaPickerPage:
        cls.require_directory_access(request)
        params = request.GET if params is None else params
        picker_type = cls.get_picker_type(params.get("picker_type"))
        is_public = cls.get_is_public(params.get("is_public"))
        item_model = cls.get_item_model(picker_type)
        cls.require_model_permission(request, Folder, "view")
        cls.require_model_permission(request, item_model, "view")
        folder = cls.get_folder(request, params.get("folder"))
        query = str(params.get("q", "")).strip()
        ordering = str(params.get("order_by", "-uploaded_at"))

        folders = tuple(cls.folder_queryset(request, folder, query, ordering))
        items = cls.item_queryset(request, picker_type)
        if is_public is not None:
            items = items.filter(is_public=is_public)
        if query:
            items = items.filter(
                models.Q(name__icontains=query)
                | models.Q(original_filename__icontains=query)
            )
        else:
            items = items.filter(folder=folder)
        items = cls.order_items(items, ordering)

        folder_count = len(folders)
        result_count = folder_count + items.count()
        paginator = Paginator(range(result_count), MEDIA_PICKER_PAGE_SIZE)
        try:
            result_page = paginator.page(params.get("page", 1))
        except PageNotAnInteger:
            result_page = paginator.page(1)
        except EmptyPage:
            result_page = paginator.page(paginator.num_pages)

        result_start = (result_page.number - 1) * MEDIA_PICKER_PAGE_SIZE
        result_end = min(result_start + MEDIA_PICKER_PAGE_SIZE, result_count)
        page_folders = folders[result_start : min(result_end, folder_count)]
        item_start = max(0, result_start - folder_count)
        item_end = max(0, result_end - folder_count)

        can_upload = cls.can_upload(request, folder)
        return MediaPickerPage(
            picker_type=picker_type,
            is_public=is_public,
            folder=folder,
            breadcrumbs=cls.get_breadcrumbs(request, folder),
            folders=page_folders,
            items=tuple(items[item_start:item_end]),
            pagination=result_page,
            can_upload=can_upload,
            can_create_folder=cls.can_create_folder(request, folder),
            upload_url=cls.upload_url(folder) if can_upload else None,
        )

    @staticmethod
    def get_picker_type(value: Any) -> str:
        picker_type = str(value or MEDIA_PICKER_TYPE_IMAGE)
        return (
            picker_type
            if picker_type in MEDIA_PICKER_TYPES
            else MEDIA_PICKER_TYPE_IMAGE
        )

    @staticmethod
    def get_is_public(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value).lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        return None

    @staticmethod
    def require_directory_access(request: HttpRequest) -> None:
        if not request.user.has_perm("filer.can_use_directory_listing"):
            raise PermissionDenied

    @staticmethod
    def get_item_model(picker_type: str):
        return (
            load_model(filer_settings.FILER_IMAGE_MODEL)
            if picker_type == MEDIA_PICKER_TYPE_IMAGE
            else load_model("filer.File")
        )

    @staticmethod
    def get_model_view(request: HttpRequest, model):
        configuration = request.request_data.configuration
        return next(
            (
                view
                for view in configuration.view_map.values()
                if getattr(view, "model", None) is model
            ),
            None,
        )

    @classmethod
    def has_model_permission(
        cls,
        request: HttpRequest,
        model,
        permission: str,
    ) -> bool:
        return SBAdminViewService.has_permission(
            request,
            view=cls.get_model_view(request, model),
            model=model,
            permission=permission,
        )

    @classmethod
    def require_model_permission(
        cls,
        request: HttpRequest,
        model,
        permission: str,
    ) -> None:
        if not cls.has_model_permission(request, model, permission):
            raise PermissionDenied

    @staticmethod
    def restricted_queryset(request: HttpRequest, model):
        return SBAdminViewService.get_restricted_queryset(
            model,
            request,
            request.request_data,
            global_filter=False,
        )

    @classmethod
    def readable_folder_queryset(cls, request: HttpRequest):
        queryset = cls.restricted_queryset(request, Folder)
        readable_ids = FolderPermission.objects.get_read_id_list(request.user)
        if readable_ids != FILER_PERMISSIONS_ALL:
            queryset = queryset.filter(
                models.Q(pk__in=readable_ids) | models.Q(owner=request.user)
            )
        return queryset

    @classmethod
    def get_breadcrumbs(
        cls,
        request: HttpRequest,
        folder: Folder | None,
    ) -> tuple[Folder, ...]:
        if folder is None:
            return ()
        path = (*folder.logical_path, folder)
        readable_ids = set(
            cls.readable_folder_queryset(request)
            .filter(pk__in=[item.pk for item in path])
            .values_list("pk", flat=True)
        )
        return tuple(item for item in path if item.pk in readable_ids)

    @classmethod
    def get_folder(cls, request: HttpRequest, value: str | None) -> Folder | None:
        if value in (None, ""):
            return None
        try:
            folder_id = int(value)
        except (TypeError, ValueError) as error:
            raise Http404 from error
        try:
            return cls.readable_folder_queryset(request).get(pk=folder_id)
        except Folder.DoesNotExist as error:
            raise Http404 from error

    @classmethod
    def folder_queryset(
        cls,
        request: HttpRequest,
        folder: Folder | None,
        query: str,
        ordering: str,
    ):
        queryset = cls.readable_folder_queryset(request)
        if query:
            queryset = queryset.filter(name__icontains=query)
        else:
            queryset = queryset.filter(parent=folder)
        return cls.order_folders(queryset, ordering)

    @staticmethod
    def order_folders(queryset, ordering: str):
        if ordering in MEDIA_PICKER_ORDERING:
            return queryset.order_by(*MEDIA_PICKER_ORDERING[ordering])
        if ordering == "-name":
            return queryset.order_by(Lower("name").desc(), "-pk")
        return queryset.order_by(Lower("name"), "pk")

    @classmethod
    def item_queryset(cls, request: HttpRequest, picker_type: str):
        model = cls.get_item_model(picker_type)
        queryset = cls.restricted_queryset(request, model)
        readable_ids = FolderPermission.objects.get_read_id_list(request.user)
        if readable_ids != FILER_PERMISSIONS_ALL:
            queryset = queryset.filter(
                models.Q(folder_id__in=readable_ids) | models.Q(owner=request.user)
            )
        return queryset.select_related("folder")

    @classmethod
    def accessible_item_queryset(cls, request: HttpRequest, picker_type: str):
        model = cls.get_item_model(picker_type)
        if not cls.has_model_permission(request, model, "view"):
            return model.objects.none()
        return cls.item_queryset(request, picker_type)

    @classmethod
    def selected_item_data(
        cls,
        request: HttpRequest,
        picker_type: str,
        value: Any,
        *,
        is_public: bool | None = None,
    ) -> dict[str, Any] | None:
        try:
            queryset = cls.accessible_item_queryset(request, picker_type)
            if is_public is not None:
                queryset = queryset.filter(is_public=is_public)
            item = queryset.filter(pk=value).first()
        except (TypeError, ValueError, ValidationError):
            return None
        return None if item is None else cls.item_data(item)

    @staticmethod
    def order_items(queryset, ordering: str):
        if ordering in MEDIA_PICKER_ORDERING:
            return queryset.order_by(*MEDIA_PICKER_ORDERING[ordering])

        display_name = Lower(
            Coalesce(
                Case(
                    When(name__exact="", then=None),
                    When(name__isnull=False, then="name"),
                ),
                "original_filename",
            )
        )
        if ordering == "-name":
            return queryset.order_by(display_name.desc(), "-pk")
        return queryset.order_by(display_name.asc(), "pk")

    @staticmethod
    def can_upload(request: HttpRequest, folder: Folder | None) -> bool:
        if not request.user.has_perm("filer.add_file"):
            return False
        if folder is None:
            return True
        return bool(folder.has_add_children_permission(request))

    @classmethod
    def can_create_folder(cls, request: HttpRequest, folder: Folder | None) -> bool:
        if not cls.has_model_permission(request, Folder, "add"):
            return False
        if not request.user.has_perm("filer.add_folder"):
            return False
        if folder is None:
            return bool(
                request.user.is_superuser
                or filer_settings.FILER_ALLOW_REGULAR_USERS_TO_ADD_ROOT_FOLDERS
            )
        return bool(
            folder.can_have_subfolders and folder.has_add_children_permission(request)
        )

    @classmethod
    def create_folder(
        cls,
        request: HttpRequest,
        *,
        parent_id: int | None,
        name: str,
    ) -> Folder:
        cls.require_directory_access(request)
        cls.require_model_permission(request, Folder, "add")
        parent = cls.get_folder(
            request,
            None if parent_id is None else str(parent_id),
        )
        if not cls.can_create_folder(request, parent):
            raise PermissionDenied

        folder = Folder(parent=parent, name=name.strip(), owner=request.user)
        try:
            folder.full_clean()
            with transaction.atomic():
                folder.save()
        except (IntegrityError, ValidationError) as error:
            if isinstance(error, ValidationError):
                raise
            raise ValidationError(
                {"name": _("A folder with this name already exists.")}
            ) from error
        clear_folder_permission_cache(request.user)
        return folder

    @classmethod
    def upload_url(cls, folder: Folder | None) -> str:
        return reverse(
            "sb_admin:filer-ajax_upload",
            kwargs=None if folder is None else {"folder_id": folder.pk},
        )

    @staticmethod
    def change_url(resource: Any) -> str:
        return reverse(
            f"sb_admin:{resource._meta.app_label}_{resource._meta.model_name}_change",
            kwargs={"object_id": resource.pk},
        )

    @classmethod
    def item_data(cls, item: Any) -> dict[str, Any]:
        model_name = item._meta.model_name
        thumbnail_url = reverse(
            f"sb_admin:filer_{model_name}_fileicon",
            kwargs={
                "file_id": item.pk,
                "size": filer_settings.FILER_THUMBNAIL_ICON_SIZE,
            },
        )
        return {
            "id": item.pk,
            "name": item.label,
            "thumbnail_url": thumbnail_url,
            "change_url": cls.change_url(item),
            "size": item._file_size,
            "uploaded_at": item.uploaded_at,
        }

    @classmethod
    def folder_data(cls, folder: Folder) -> dict[str, Any]:
        return {
            "id": folder.pk,
            "name": folder.name,
            "change_url": cls.change_url(folder),
        }

    @classmethod
    def page_data(cls, page: MediaPickerPage) -> dict[str, Any]:
        return {
            "picker_type": page.picker_type,
            "is_public": page.is_public,
            "folder": (None if page.folder is None else cls.folder_data(page.folder)),
            "breadcrumbs": [cls.folder_data(folder) for folder in page.breadcrumbs],
            "folders": [cls.folder_data(folder) for folder in page.folders],
            "items": [cls.item_data(item) for item in page.items],
            "pagination": page.pagination,
            "permissions": {
                "can_upload": page.can_upload,
                "can_create_folder": page.can_create_folder,
            },
            "upload": {
                "url": page.upload_url,
                "max_files": filer_settings.FILER_UPLOADER_MAX_FILES,
                "max_file_size": filer_settings.FILER_UPLOADER_MAX_FILE_SIZE,
                "connections": filer_settings.FILER_UPLOADER_CONNECTIONS,
            },
        }
