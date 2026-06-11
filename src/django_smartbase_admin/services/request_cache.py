from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

_MISSING = object()
_REQUEST_CACHE_ATTR = "_sbadmin_request_cache"

T = TypeVar("T")


class RequestCacheKey:
    USER_CONFIG = "services.configuration.user_config"

    @classmethod
    def autocomplete_selected_options(
        cls, widget_id: str, formset_prefix: str, value_field: str
    ) -> str:
        return ":".join(
            (
                "admin.widgets.autocomplete.selected_options",
                widget_id,
                formset_prefix,
                value_field,
            )
        )


def get_request():
    try:
        return SBAdminThreadLocalService.get_request()
    except LookupError:
        return None


def cache_on_request(key: str, factory: Callable[[], T], request=None) -> T:
    request = request or get_request()
    if request is None:
        return factory()
    cache = getattr(request, _REQUEST_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(request, _REQUEST_CACHE_ATTR, cache)
    cached = cache.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    value = factory()
    cache[key] = value
    return value
