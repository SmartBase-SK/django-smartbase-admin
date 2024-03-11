from django.core.exceptions import ImproperlyConfigured

from django_smartbase_admin.services.configuration import SBAdminConfigurationService


class SBAdminMenuItem(object):
    view_id = None
    view = None
    icon = None
    label = None
    url = None
    sub_items = None
    is_active = None
    parent_menu_item = None

    def __init__(
        self,
        view_id=None,
        icon=None,
        label=None,
        url=None,
        sub_items=None,
    ) -> None:
        super().__init__()
        self.view_id = view_id or self.view_id
        self.icon = icon or self.icon
        self.label = label or self.label
        self.url = url or self.url
        self.sub_items = sub_items or self.sub_items or []

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
        return (
            self.url
            or (self.view.get_menu_view_url(request) if self.view else None)
            or ""
        )

    def get_icon(self):
        return self.icon or getattr(self.view, "icon", None)

    def get_subitems_serialized(self, request, request_data):
        subitem_active = False
        subitems_serialized = []
        for item in self.sub_items:
            item_dict, item_active = item.process_and_serialize(request, request_data)
            subitems_serialized.append(item_dict)
            subitem_active = item_active or subitem_active
        return subitems_serialized, subitem_active

    def process_and_serialize(self, request, request_data):
        sub_items, subitem_active = self.get_subitems_serialized(request, request_data)
        active = subitem_active or request_data.view == self.get_id()
        json_dict = {
            "sub_items": sub_items,
            "get_label": self.get_label(),
            "get_icon": self.get_icon(),
            "get_url": self.get_url(request),
            "get_id": self.get_id(),
            "get_view_id": self.get_view_id(),
            "is_active": active,
        }
        return json_dict, active
