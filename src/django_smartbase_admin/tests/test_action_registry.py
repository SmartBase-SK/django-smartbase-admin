"""Browser and MCP modal lookup must agree across action sources."""

from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.contrib.auth.models import Group, User
from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from django.views import View

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import SBAdminFormViewAction
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView
from django_smartbase_admin.engine.admin_view import SBAdminView
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.mcp.actions import SBAdminMCPActionFormService
from django_smartbase_admin.services.views import SBAdminViewService

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


class RegistryModal(View):
    view = None

    def get(self, request, *args, **kwargs):
        return HttpResponse(f"{self.view.get_id()}:{kwargs.get('object_id')}")


class RegistryCustomView(SBAdminView):
    view_id = "registry_custom_view"
    source = "detail"
    expected_object_id = "7"

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def has_permission_for_action(self, request, action):
        return request.allow_actions and action.target_view is RegistryModal

    def modal_actions(self, request, source):
        if self.source != source or not request.publish_actions:
            return []
        return [
            SBAdminFormViewAction(
                title="Registry modal", target_view=RegistryModal, view=self
            )
        ]

    def get_sbadmin_detail_actions(self, request, object_id=None):
        if object_id != self.expected_object_id:
            return []
        return self.modal_actions(request, "detail")

    def get_sbadmin_fieldsets(self, request, object_id=None):
        if object_id != self.expected_object_id:
            return []
        return [(None, {"actions": self.modal_actions(request, "fieldset")})]

    def get_sbadmin_modal_actions(self, request):
        return self.modal_actions(request, "markup")


class RegistryListView(RegistryCustomView, SBAdminBaseListView):
    sbadmin_list_history_enabled = False

    def get_sbadmin_list_selection_actions(self, request):
        return []

    def get_sbadmin_list_actions(self, request):
        return self.modal_actions(request, "list")


class RegistryMembershipInline(SBAdminTableInline):
    model = User.groups.through

    def has_permission(self, request, obj=None, permission=None):
        return True

    def has_permission_for_action(self, request, action):
        return request.allow_actions and action.target_view is RegistryModal

    def get_sbadmin_fieldsets(self, request, object_id=None):
        # Only the inline built for the parent page publishes this action.
        if self.parent_instance is None or not request.publish_actions:
            return []
        return [
            (
                None,
                {
                    "fields": ("user",),
                    "actions": [
                        SBAdminFormViewAction(
                            title=f"Group {self.parent_instance.pk}",
                            target_view=RegistryModal,
                            view=self,
                        )
                    ],
                },
            )
        ]


class RegistryGroupAdmin(SBAdmin):
    inlines = [RegistryMembershipInline]

    def has_view_or_change_permission(self, request, obj=None):
        return request.allow_parent

    def get_object(self, request, object_id, from_field=None):
        if str(object_id) == "7":
            return Group(pk=7, name="Registry group")
        return None


@override_settings(ROOT_URLCONF=__name__)
class ActionRegistryTests(SimpleTestCase):
    def request_for(self, view, *, object_id="7", method="get"):
        request = getattr(RequestFactory(), method)("/")
        request.allow_actions = True
        request.publish_actions = True
        request.allow_parent = True
        request.request_data = SBAdminViewRequestData(
            view=view.get_id(),
            action="RegistryModal",
            modifier="template",
            user=None,
            object_id=object_id,
        )
        request.request_data.selected_view = view
        return request

    def dispatch(self, request):
        with patch.object(
            SBAdminViewRequestData,
            "from_request_and_kwargs",
            return_value=request.request_data,
        ):
            return SBAdminViewService.delegate_to_action(request)

    def inline_view(self):
        site = AdminSite()
        site.register(Group, RegistryGroupAdmin)
        return RegistryMembershipInline(Group, site)

    def test_custom_view_dispatch_discovers_detail_fieldset_and_markup_modals(self):
        for source in ("detail", "fieldset", "markup"):
            with self.subTest(source=source):
                view = RegistryCustomView()
                view.source = source

                response = self.dispatch(self.request_for(view))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"registry_custom_view:7")
                self.assertFalse(hasattr(view, "RegistryModal"))

    def test_detail_and_fieldset_lookup_without_object_skips_getters(self):
        for view_class in (RegistryCustomView, RegistryListView):
            for source in ("detail", "fieldset"):
                with self.subTest(view=view_class.__name__, source=source):
                    view = view_class()
                    view.source = source
                    view.expected_object_id = None
                    with (
                        patch.object(
                            view,
                            "get_sbadmin_detail_actions",
                            wraps=view.get_sbadmin_detail_actions,
                        ) as detail_actions,
                        patch.object(
                            view,
                            "get_sbadmin_fieldsets",
                            wraps=view.get_sbadmin_fieldsets,
                        ) as fieldsets,
                    ):
                        with self.assertRaises(Http404):
                            self.dispatch(self.request_for(view, object_id=None))
                        with self.assertRaises(LookupError):
                            SBAdminMCPActionFormService._find_modal_action(
                                view,
                                "RegistryModal",
                                self.request_for(view, object_id=None),
                            )

                        detail_actions.assert_not_called()
                        fieldsets.assert_not_called()

    def test_list_and_markup_modals_without_object_dispatch(self):
        for source in ("list", "markup"):
            with self.subTest(source=source):
                view = RegistryListView()
                view.source = source

                response = self.dispatch(self.request_for(view, object_id=None))
                action, target = SBAdminMCPActionFormService._find_modal_action(
                    view,
                    "RegistryModal",
                    self.request_for(view, object_id=None),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"registry_custom_view:None")
                self.assertIs(target, RegistryModal)
                self.assertEqual(action.url, view.get_action_url("RegistryModal"))

    def test_modal_without_explicit_view_uses_dispatching_view(self):
        view = RegistryCustomView()
        action = SBAdminFormViewAction(
            title="Registry modal", target_view=RegistryModal
        )

        with patch.object(view, "get_sbadmin_detail_actions", return_value=[action]):
            response = self.dispatch(self.request_for(view))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"registry_custom_view:7")

    def test_mcp_discovers_custom_view_actions_and_honors_explicit_object(self):
        for source in ("detail", "fieldset", "markup"):
            with self.subTest(source=source):
                view = RegistryCustomView()
                view.source = source
                request = self.request_for(view, object_id=None)

                action, target = SBAdminMCPActionFormService._find_modal_action(
                    view, "RegistryModal", request, object_id="7"
                )

                self.assertIs(target, RegistryModal)
                self.assertIs(action, view.find_action(request, "RegistryModal"))
                self.assertEqual(
                    action.url, view.get_action_url("RegistryModal", object_id="7")
                )

    def test_hidden_or_denied_modals_are_unavailable_to_browser_and_mcp(self):
        view = RegistryCustomView()
        view.source = "markup"
        self.dispatch(self.request_for(view))

        for denied_attribute in ("allow_actions", "publish_actions"):
            with self.subTest(denied_attribute=denied_attribute):
                request = self.request_for(view)
                setattr(request, denied_attribute, False)
                with self.assertRaises(Http404):
                    self.dispatch(request)
                with self.assertRaises(LookupError):
                    SBAdminMCPActionFormService._find_modal_action(
                        view, "RegistryModal", request, object_id="7"
                    )

    def test_list_view_lookup_honors_explicit_object_after_initialization(self):
        for source in ("detail", "fieldset"):
            with self.subTest(source=source):
                view = RegistryListView()
                view.source = source
                request = self.request_for(view, object_id=None)
                view.init_actions(request)

                action, target = SBAdminMCPActionFormService._find_modal_action(
                    view, "RegistryModal", request, object_id="7"
                )

                self.assertIs(target, RegistryModal)
                self.assertEqual(
                    action.url, view.get_action_url("RegistryModal", object_id="7")
                )

    def test_parent_inline_registration_requires_accessible_object(self):
        view = RegistryGroupAdmin(Group, AdminSite())
        for object_id, allow_parent in ((None, True), ("8", True), ("7", False)):
            with self.subTest(object_id=object_id, allow_parent=allow_parent):
                request = self.request_for(view, object_id=object_id)
                request.allow_parent = allow_parent
                with (
                    patch.object(view, "_list_actions_processed", return_value=[]),
                    patch.object(view, "get_sbadmin_fieldsets", return_value=[]),
                    patch.object(
                        view, "get_inline_instances", return_value=[]
                    ) as inline_instances,
                ):
                    view.init_actions(request)
                    with self.assertRaises(Http404):
                        SBAdminViewService.delegate_to_modal_action(
                            request, view, "MissingModal"
                        )

                    inline_instances.assert_not_called()

    def test_inline_lookup_without_object_skips_getters_and_parent_inlines(self):
        view = self.inline_view()
        parent_admin = view.admin_site._registry[Group]
        with (
            patch.object(parent_admin, "get_inline_instances") as inline_instances,
            patch.object(
                view,
                "get_sbadmin_inline_list_actions",
                wraps=view.get_sbadmin_inline_list_actions,
            ) as inline_actions,
            patch.object(
                view, "get_sbadmin_fieldsets", wraps=view.get_sbadmin_fieldsets
            ) as fieldsets,
        ):
            view.init_actions(self.request_for(view, object_id=None))
            with self.assertRaises(Http404):
                self.dispatch(self.request_for(view, object_id=None))
            with self.assertRaises(LookupError):
                SBAdminMCPActionFormService._find_modal_action(
                    view,
                    "RegistryModal",
                    self.request_for(view, object_id=None),
                )

            inline_instances.assert_not_called()
            inline_actions.assert_not_called()
            fieldsets.assert_not_called()

    def test_inline_fieldset_dispatch_rebuilds_parent_context(self):
        for method in ("get", "post"):
            with self.subTest(method=method):
                view = self.inline_view()
                request = self.request_for(view, method=method)

                def render_parent(modal, request, *args, **kwargs):
                    parent = modal.view.parent_instance
                    response = HttpResponse(f"{modal.view.get_id()}:{parent.pk}")
                    self.assertIs(
                        modal.view, view.find_action(request, "RegistryModal").view
                    )
                    return response

                with patch.object(RegistryModal, method, render_parent, create=True):
                    response = self.dispatch(request)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content.decode(), f"{view.get_id()}:7")
                self.assertIsNone(view.parent_instance)

    def test_mcp_finds_inline_fieldset_with_fresh_and_registered_actions(self):
        for bound in (False, True):
            with self.subTest(parent_bound=bound):
                view = self.inline_view()
                request = self.request_for(view, object_id=None)
                if bound:
                    view.init_inline_dynamic(request, Group(pk=7))
                    view.init_actions(request)

                action, target = SBAdminMCPActionFormService._find_modal_action(
                    view, "RegistryModal", request, object_id="7"
                )

                self.assertIs(target, RegistryModal)
                self.assertEqual(action.title, "Group 7")
                self.assertEqual(
                    action.url, view.get_action_url("RegistryModal", object_id=7)
                )

    def test_inline_lookup_preserves_parent_and_action_permissions(self):
        view = self.inline_view()
        self.dispatch(self.request_for(view))

        for denied_attribute in ("allow_parent", "allow_actions", "publish_actions"):
            with self.subTest(denied_attribute=denied_attribute):
                request = self.request_for(view)
                setattr(request, denied_attribute, False)
                with self.assertRaises(Http404):
                    self.dispatch(request)
                with self.assertRaises(LookupError):
                    SBAdminMCPActionFormService._find_modal_action(
                        view, "RegistryModal", request, object_id="7"
                    )

        with self.assertRaises(Http404):
            self.dispatch(self.request_for(view, object_id="8"))
