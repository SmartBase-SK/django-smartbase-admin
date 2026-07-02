from types import SimpleNamespace

from django_smartbase_admin.engine.menu_item import SBAdminMenuItem


def test_menu_item_serializes_css_class():
    item = SBAdminMenuItem(
        label="Feedback",
        url="/feedback/",
        css_class="feedback-menu-item",
    )

    serialized, active = item.process_and_serialize(None, SimpleNamespace(view=None))

    assert active is False
    assert serialized["get_css_class"] == "feedback-menu-item"
