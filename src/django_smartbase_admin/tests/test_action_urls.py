"""Action URL rendering catches typos without rejecting declared modals."""

from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth.models import Group, User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path, reverse
from django.views import View

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminFormViewAction,
    sbadmin_action,
)
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class ArchiveModal(View):
    pass


class NamedArchiveModal(ArchiveModal):
    action_id = "archive_dialog"


class ActionURLAdmin(SBAdmin):
    def has_permission_for_action(self, request, action):
        return True

    @sbadmin_action
    def action_archive(self, request, modifier, object_id):
        return HttpResponse("archived")


class PrefixedActionURLAdmin(ActionURLAdmin):
    def get_action_url(self, action, modifier="template", object_id=None):
        return f"/custom{super().get_action_url(action, modifier, object_id)}"


@override_settings(ROOT_URLCONF=__name__)
class ActionURLTests(SimpleTestCase):
    def setUp(self):
        self.view = ActionURLAdmin(Group, AdminSite())
        self.request = RequestFactory().get("/")
        self.request.request_data = SBAdminViewRequestData(
            view=self.view.get_id(), action=None, modifier=None, user=None
        )

    def test_unknown_action_names_fail_when_building_urls(self):
        # Loading a modal class alone does not declare it on this admin.
        for action_id in ("action_archve", "ArchiveModal"):
            with self.subTest(action_id=action_id):
                with self.assertRaisesMessage(ImproperlyConfigured, action_id):
                    self.view.get_action_url(action_id)

    def test_method_action_urls_preserve_parameters(self):
        self.assertEqual(
            self.view.get_action_url("action_archive", "selected", object_id="7"),
            reverse(
                "sb_admin:sb_admin_base",
                kwargs={
                    "view": self.view.get_id(),
                    "action": "action_archive",
                    "modifier": "selected",
                    "object_id": "7",
                },
            ),
        )

    def test_mistyped_action_declarations_fail_during_processing(self):
        for processor in (
            self.view.process_list_actions,
            self.view.process_detail_actions,
            self.view.process_row_actions,
            self.view.process_inline_actions,
        ):
            for nested in (False, True):
                with self.subTest(processor=processor.__name__, nested=nested):
                    action = SBAdminCustomAction(
                        title="Archive", view=self.view, action_id="action_archve"
                    )
                    if nested:
                        action = SBAdminCustomAction(title="More", sub_actions=[action])
                    with self.assertRaisesMessage(
                        ImproperlyConfigured, "action_archve"
                    ):
                        processor(self.request, [action])

    def test_modal_ids_preserve_destination_and_custom_url_hooks(self):
        destination = PrefixedActionURLAdmin(User, AdminSite())
        for modal, explicit_id, expected_id in (
            (ArchiveModal, None, "ArchiveModal"),
            (NamedArchiveModal, None, "archive_dialog"),
            (NamedArchiveModal, "archive_selected", "archive_selected"),
        ):
            with self.subTest(action_id=expected_id):
                action = SBAdminFormViewAction(
                    title="Archive",
                    target_view=modal,
                    view=destination,
                    action_id=explicit_id,
                    action_modifier="selected",
                )
                processed = self.view.process_detail_actions(
                    self.request, [action], object_id="7"
                )[0]

                self.assertEqual(
                    processed.url,
                    "/custom"
                    + reverse(
                        "sb_admin:sb_admin_base",
                        kwargs={
                            "view": destination.get_id(),
                            "action": expected_id,
                            "modifier": "selected",
                            "object_id": "7",
                        },
                    ),
                )
                self.assertIsNone(action.url)
                self.assertFalse(hasattr(destination, expected_id))

    def test_registered_modal_urls_are_scoped_to_request_and_view(self):
        action = SBAdminFormViewAction(title="Archive", target_view=ArchiveModal)
        processed = self.view.process_list_actions(self.request, [action])[0]

        with patch.object(
            SBAdminThreadLocalService, "get_request", return_value=self.request
        ):
            self.assertEqual(self.view.get_action_url("ArchiveModal"), processed.url)
            other_view = ActionURLAdmin(User, AdminSite())
            with self.assertRaisesMessage(ImproperlyConfigured, "ArchiveModal"):
                other_view.get_action_url("ArchiveModal")

        with patch.object(SBAdminThreadLocalService, "get_request", return_value=None):
            with self.assertRaisesMessage(ImproperlyConfigured, "ArchiveModal"):
                self.view.get_action_url("ArchiveModal")

    def test_url_resolution_does_not_register_denied_modals(self):
        action = SBAdminFormViewAction(title="Archive", target_view=ArchiveModal)

        def deny_action(request, action):
            self.assertEqual(request.request_data.action_map, {})
            return False

        with patch.object(
            self.view, "has_permission_for_action", side_effect=deny_action
        ):
            self.assertEqual(self.view.process_list_actions(self.request, [action]), [])

        self.assertEqual(self.request.request_data.action_map, {})
        with patch.object(
            SBAdminThreadLocalService, "get_request", return_value=self.request
        ):
            with self.assertRaisesMessage(ImproperlyConfigured, "ArchiveModal"):
                self.view.get_action_url("ArchiveModal")

    def test_failed_modal_url_resolution_does_not_leave_name_allowed(self):
        action = SBAdminFormViewAction(title="Archive", target_view=ArchiveModal)
        with patch.object(
            self.view, "get_action_url", side_effect=ValueError("bad URL")
        ):
            with self.assertRaisesMessage(ValueError, "bad URL"):
                self.view.process_list_actions(self.request, [action])

        with self.assertRaisesMessage(ImproperlyConfigured, "ArchiveModal"):
            self.view.get_action_url("ArchiveModal")
