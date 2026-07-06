from types import SimpleNamespace

from django_smartbase_admin.engine.menu_item import SBAdminMenuItem


class MenuView:
    def __init__(self, view_id, *, url="/view/", module_allowed=True, perms=None):
        self.view_id = view_id
        self.url = url
        self.module_allowed = module_allowed
        self.perms = perms or {"view": True}
        self.permission_check_count = 0

    def get_id(self):
        return self.view_id

    def get_menu_label(self):
        return self.view_id

    def get_menu_view_url(self, request):
        return self.url

    def has_module_permission(self, request):
        return self.module_allowed

    def get_model_perms(self, request):
        self.permission_check_count += 1
        return self.perms

    def has_view_permission(self, request):
        self.permission_check_count += 1
        return self.perms.get("view", False)

    def has_change_permission(self, request):
        self.permission_check_count += 1
        return self.perms.get("change", False)

    def has_add_permission(self, request):
        self.permission_check_count += 1
        return self.perms.get("add", False)

    def has_delete_permission(self, request):
        self.permission_check_count += 1
        return self.perms.get("delete", False)


class MenuPermissionView(MenuView):
    def __init__(self, view_id, *, menu_allowed):
        super().__init__(view_id, module_allowed=False)
        self.menu_allowed = menu_allowed

    def has_menu_permission(self, request):
        return self.menu_allowed


def menu_item_for_view(view):
    item = SBAdminMenuItem(view_id=view.get_id())
    item.view = view
    return item


def test_menu_item_serializes_css_class():
    item = SBAdminMenuItem(
        label="Feedback",
        url="/feedback/",
        css_class="feedback-menu-item",
    )

    serialized, active = item.process_and_serialize(None, SimpleNamespace(view=None))

    assert active is False
    assert serialized["get_css_class"] == "feedback-menu-item"


def test_menu_item_without_permissions_is_not_serialized():
    view = MenuView(
        "hidden",
        perms={"add": False, "change": False, "delete": False, "view": False},
    )
    item = menu_item_for_view(view)

    serialized, active = item.process_and_serialize(
        SimpleNamespace(), SimpleNamespace(view=None)
    )

    assert serialized is None
    assert active is False


def test_parent_menu_item_keeps_only_permitted_children():
    visible_view = MenuView("visible", url="/visible/")
    hidden_view = MenuView(
        "hidden",
        perms={"add": False, "change": False, "delete": False, "view": False},
    )
    parent = SBAdminMenuItem(
        label="Settings",
        sub_items=[
            menu_item_for_view(visible_view),
            menu_item_for_view(hidden_view),
        ],
    )

    serialized, active = parent.process_and_serialize(
        SimpleNamespace(), SimpleNamespace(view="visible")
    )

    assert active is True
    assert len(serialized["sub_items"]) == 1
    assert serialized["sub_items"][0]["get_id"] == "visible"


def test_parent_menu_item_with_denied_view_uses_first_child_url():
    parent_view = MenuView(
        "parent",
        url="/parent/",
        perms={"add": False, "change": False, "delete": False, "view": False},
    )
    child_view = MenuView("child", url="/child/")
    parent = menu_item_for_view(parent_view)
    parent.sub_items = [menu_item_for_view(child_view)]

    serialized, active = parent.process_and_serialize(
        SimpleNamespace(), SimpleNamespace(view=None)
    )

    assert active is False
    assert serialized["get_url"] == ""
    assert serialized["sub_items"][0]["get_url"] == "/child/"


def test_menu_permission_is_cached_per_request():
    view = MenuView("cached")
    request_data = SimpleNamespace(view=None)

    request = SimpleNamespace()

    menu_item_for_view(view).process_and_serialize(request, request_data)
    menu_item_for_view(view).process_and_serialize(request, request_data)

    assert view.permission_check_count == 1


def test_menu_permission_hook_overrides_model_permission_checks():
    view = MenuPermissionView("menu-visible", menu_allowed=True)
    item = menu_item_for_view(view)

    serialized, active = item.process_and_serialize(
        SimpleNamespace(), SimpleNamespace(view=None)
    )

    assert active is False
    assert serialized["get_id"] == "menu-visible"
    assert view.permission_check_count == 0


def test_menu_item_uses_selected_view_menu_highlight_id_for_active_state():
    menu_view = MenuView("connector")
    item = menu_item_for_view(menu_view)
    request_data = SimpleNamespace(
        view="connector_orders",
        selected_view=SimpleNamespace(menu_highlight_view_id="connector"),
    )

    serialized, active = item.process_and_serialize(SimpleNamespace(), request_data)

    assert active is True
    assert serialized["is_active"] is True
