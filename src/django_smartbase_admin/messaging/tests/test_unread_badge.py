"""Tests for the menu-item badge mechanism + messaging unread count.

Covers the reusable ``SBAdminMenuItem.badge`` hook and the messaging
``get_unread_count`` helper that projects wire together to show an
unread-message badge on the inbox menu entry.
"""

from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils.html import format_html
from django.utils.safestring import SafeString

from django_smartbase_admin.engine.menu_item import (
    DEFAULT_MENU_ITEM_BADGE_CLASS,
    SBAdminMenuItem,
)
from django_smartbase_admin.messaging.config import SBAdminMessagingConfig
from django_smartbase_admin.messaging.models import Message, MessageRecipient
from django_smartbase_admin.messaging.services import SBAdminMessagingService


class _PermittedView:
    def get_id(self):
        return "inbox"

    def get_menu_view_url(self, request):
        return "/inbox/"

    def has_view_permission(self, request):
        return True


class MenuItemBadgeTestCase(SimpleTestCase):
    def test_static_badge_value(self):
        item = SBAdminMenuItem(label="Inbox", badge=3)
        self.assertEqual(item.get_badge(request=None), 3)

    def test_callable_badge_receives_request(self):
        sentinel = object()
        seen = {}

        def badge(request):
            seen["request"] = request
            return 5

        item = SBAdminMenuItem(label="Inbox", badge=badge)
        self.assertEqual(item.get_badge(sentinel), 5)
        self.assertIs(seen["request"], sentinel)

    def test_falsy_badge_is_normalised_to_none(self):
        # 0 / "" should render no badge.
        self.assertIsNone(SBAdminMenuItem(label="Inbox", badge=0).get_badge(None))
        self.assertIsNone(
            SBAdminMenuItem(label="Inbox", badge=lambda r: 0).get_badge(None)
        )
        self.assertIsNone(SBAdminMenuItem(label="Inbox").get_badge(None))

    def test_render_badge_wraps_value_with_default_classes(self):
        html = SBAdminMenuItem(label="Inbox", badge=7).render_badge(None)
        self.assertIsInstance(html, SafeString)
        self.assertEqual(
            html,
            format_html('<span class="{}">{}</span>', DEFAULT_MENU_ITEM_BADGE_CLASS, 7),
        )

    def test_render_badge_uses_custom_class(self):
        html = SBAdminMenuItem(
            label="Inbox", badge=2, badge_class="badge badge-primary"
        ).render_badge(None)
        self.assertEqual(html, '<span class="badge badge-primary">2</span>')

    def test_render_badge_escapes_plain_value(self):
        html = SBAdminMenuItem(label="Inbox", badge="<b>x</b>").render_badge(None)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)

    def test_render_badge_passes_safe_html_through(self):
        markup = format_html('<span class="custom">{}</span>', "9")
        html = SBAdminMenuItem(label="Inbox", badge=lambda r: markup).render_badge(None)
        self.assertEqual(html, markup)

    def test_render_badge_none_when_empty(self):
        self.assertIsNone(SBAdminMenuItem(label="Inbox").render_badge(None))
        self.assertIsNone(SBAdminMenuItem(label="Inbox", badge=0).render_badge(None))

    def test_serialization_includes_rendered_badge(self):
        item = SBAdminMenuItem(label="Inbox", badge=lambda r: 7)
        item.view = _PermittedView()
        request_data = SimpleNamespace(view="other")
        json_dict, _active = item.process_and_serialize(
            request=None, request_data=request_data
        )
        self.assertIsInstance(json_dict["get_badge"], SafeString)
        self.assertIn(">7</span>", json_dict["get_badge"])


class _Configuration:
    def __init__(self, messaging_config):
        self.messaging_config = messaging_config


def _request(user, messaging_config):
    request = RequestFactory().get("/")
    request.user = user
    request.request_data = SimpleNamespace(
        configuration=_Configuration(messaging_config)
    )
    return request


class GetUnreadCountTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="u1")
        cls.other = User.objects.create_user(username="u2")
        message = Message.objects.create(title="Hello", type="info")
        # Two unread for user, one read, one for the other user.
        MessageRecipient.objects.create(message=message, user=cls.user)
        m2 = Message.objects.create(title="Second", type="info")
        MessageRecipient.objects.create(message=m2, user=cls.user)
        m3 = Message.objects.create(title="Read", type="info")
        from django.utils import timezone

        MessageRecipient.objects.create(
            message=m3, user=cls.user, read_at=timezone.now()
        )
        MessageRecipient.objects.create(message=message, user=cls.other)

    def test_counts_only_unread_for_user(self):
        request = _request(self.user, SBAdminMessagingConfig())
        self.assertEqual(SBAdminMessagingService.get_unread_count(request), 2)

    def test_zero_when_messaging_disabled(self):
        request = _request(self.user, None)
        self.assertEqual(SBAdminMessagingService.get_unread_count(request), 0)

    def test_zero_for_anonymous_user(self):
        request = _request(AnonymousUser(), SBAdminMessagingConfig())
        self.assertEqual(SBAdminMessagingService.get_unread_count(request), 0)
