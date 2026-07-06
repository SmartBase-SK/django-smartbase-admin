from django.core.exceptions import ImproperlyConfigured
from django.utils.html import format_html
from django.utils.safestring import SafeString

from django_smartbase_admin.services.configuration import SBAdminConfigurationService
from django_smartbase_admin.services.request_cache import cache_on_request

DEFAULT_MENU_ITEM_BADGE_CLASS = "badge badge-simple badge-primary ml-auto"


class SBAdminMenuItem(object):
    view_id = None
    view = None
    icon = None
    label = None
    url = None
    sub_items = None
    is_active = None
    parent_menu_item = None
    badge = None
    badge_class = DEFAULT_MENU_ITEM_BADGE_CLASS
    css_class = None

    def __init__(
        self,
        view_id=None,
        icon=None,
        label=None,
        url=None,
        sub_items=None,
        badge=None,
        badge_class=None,
        css_class=None,
    ) -> None:
        super().__init__()
        self.view_id = view_id or self.view_id
        self.icon = icon or self.icon
        self.label = label or self.label
        self.url = url or self.url
        self.sub_items = sub_items or self.sub_items or []
        self.badge = badge if badge is not None else self.badge
        self.badge_class = badge_class or self.badge_class
        self.css_class = css_class if css_class is not None else self.css_class or ""

    @classmethod
    def init_menu_item_static_cls(cls, menu_item, view_id, view_map):
        if not view_id:
            return
        menu_item.view = view_map.get(view_id, None)
        if not menu_item.view:
            raise ImproperlyConfigured(
                f"Menu item {menu_item} is missing view {view_id}"
            )

    def init_menu_item_static(self, view_map):
        self.init_menu_item_static_cls(self, self.get_view_id(), view_map)
        for sub_item in self.sub_items:
            self.init_menu_item_static_cls(sub_item, sub_item.get_view_id(), view_map)
            sub_item.parent_menu_item = self

    def get_view_id(self):
        return self.view_id

    def get_id(self):
        label_id = SBAdminConfigurationService.get_view_url_identifier(self.label)
        view_id = self.view.get_id() if self.view else None
        return view_id or label_id

    def get_label(self):
        return self.label or self.view.get_menu_label()

    def get_url(self, request):
        if callable(self.url):
            return self.url(request)
        elif self.url:
            return self.url
        elif self.view:
            return self.view.get_menu_view_url(request)
        else:
            return ""

    def get_icon(self):
        return self.icon or getattr(self.view, "icon", None)

    def get_badge(self, request):
        badge = self.badge
        if callable(badge):
            badge = badge(request)
        return badge or None

    def get_css_class(self):
        return self.css_class or ""

    def get_badge_class(self, request):
        return self.badge_class

    def render_badge(self, request):
        badge = self.get_badge(request)
        if badge is None:
            return None
        if isinstance(badge, SafeString):
            return badge
        return format_html(
            '<span class="{}">{}</span>', self.get_badge_class(request), badge
        )

    def has_view_menu_permission(self, request):
        if not self.view:
            return True

        has_menu_permission = getattr(self.view, "has_menu_permission", None)
        if callable(has_menu_permission):
            return has_menu_permission(request)

        permission_checks = (
            "has_view_permission",
            "has_change_permission",
            "has_add_permission",
            "has_delete_permission",
        )
        checked_any_permission = False
        for permission_check_name in permission_checks:
            permission_check = getattr(self.view, permission_check_name, None)
            if not callable(permission_check):
                continue
            checked_any_permission = True
            if permission_check(request):
                return True

        if checked_any_permission:
            return False

        return True

    def has_menu_permission(self, request, request_data):
        if not self.view:
            return True

        cache_key = f"engine.menu_item.has_menu_permission:{self.view.get_id()}"
        return cache_on_request(
            cache_key,
            lambda: self.has_view_menu_permission(request),
            request=request,
        )

    def get_active_menu_view_id(self, request, request_data):
        selected_view = getattr(request_data, "selected_view", None) or getattr(
            request, "sbadmin_selected_view", None
        )
        return (
            getattr(selected_view, "menu_highlight_view_id", None) or request_data.view
        )

    def get_subitems_serialized(self, request, request_data):
        subitem_active = False
        subitems_serialized = []
        for item in self.sub_items:
            item_dict, item_active = item.process_and_serialize(request, request_data)
            if item_dict is None:
                continue
            subitems_serialized.append(item_dict)
            subitem_active = item_active or subitem_active
        return subitems_serialized, subitem_active

    def process_and_serialize(self, request, request_data):
        sub_items, subitem_active = self.get_subitems_serialized(request, request_data)
        has_menu_permission = self.has_menu_permission(request, request_data)
        # Root menu item without permissions.
        if not has_menu_permission and not sub_items:
            return None, False
        # Root wrapper menu item without visible children.
        if not self.view and not sub_items:
            return None, False
        active = (
            subitem_active
            or self.get_active_menu_view_id(request, request_data) == self.get_id()
        )
        json_dict = {
            "sub_items": sub_items,
            "get_label": self.get_label(),
            "get_icon": self.get_icon(),
            "get_url": self.get_url(request) if has_menu_permission else "",
            "get_id": self.get_id(),
            "get_view_id": self.get_view_id(),
            "get_badge": self.render_badge(request),
            "get_css_class": self.get_css_class(),
            "is_active": active,
        }
        return json_dict, active
