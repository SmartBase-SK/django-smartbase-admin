import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from filer.models import Folder

from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.admin_base_view import (
    SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR,
    SBADMIN_PARENT_INSTANCE_LABEL_VAR,
    SBADMIN_PARENT_INSTANCE_PK_VAR,
)
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService


class ForwardedFkReachabilityTest(TestCase):
    def setUp(self):
        self.visible = Folder.objects.create(name="visible")
        self.hidden = Folder.objects.create(name="hidden")

    def _widget(self, restricted_qs):
        widget = SBAdminAutocompleteWidget.__new__(SBAdminAutocompleteWidget)
        widget.form_field = SimpleNamespace(error_messages={"invalid_choice": "bad"})
        form = SimpleNamespace(
            model=Folder,
            fields={
                "parent": SimpleNamespace(
                    queryset=restricted_qs,
                    widget=SimpleNamespace(),
                )
            },
        )
        widget.form = form
        return widget, form

    def _raw(self, pk):
        return json.dumps([{"value": pk, "label": "x"}])

    def test_unreachable_fk_raises(self):
        widget, form = self._widget(Folder.objects.filter(pk=self.visible.pk))
        with self.assertRaises(ValidationError):
            widget._validate_forwarded_value(
                None, form, Folder, "parent", self._raw(self.hidden.pk)
            )

    def test_reachable_fk_passes(self):
        widget, form = self._widget(Folder.objects.filter(pk=self.visible.pk))
        widget._validate_forwarded_value(
            None, form, Folder, "parent", self._raw(self.visible.pk)
        )


class AutocompleteCreatePermissionTest(TestCase):
    def _check(self, admin_for_model):
        widget = SBAdminAutocompleteWidget.__new__(SBAdminAutocompleteWidget)
        registry = {Folder: admin_for_model} if admin_for_model else {}
        with patch.dict(
            "django_smartbase_admin.admin.site.sb_admin_site._registry",
            registry,
            clear=False,
        ):
            widget._check_create_permission(MagicMock(user=MagicMock()), Folder)

    def test_denied_when_admin_rejects(self):
        admin = MagicMock()
        admin.has_add_permission.return_value = False
        with self.assertRaises(PermissionDenied):
            self._check(admin)

    def test_allowed_when_admin_accepts(self):
        admin = MagicMock()
        admin.has_add_permission.return_value = True
        self._check(admin)


class AutocompleteParentPreselectTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.parent = Folder.objects.create(name="parent")
        self.existing = Folder.objects.create(name="existing")

    def tearDown(self):
        SBAdminThreadLocalService.clear_request()

    def _request(self, parent_field="modal_folder_parent"):
        request = self.factory.get(
            "/",
            data={
                SBADMIN_PARENT_INSTANCE_FIELD_NAME_VAR: parent_field,
                SBADMIN_PARENT_INSTANCE_PK_VAR: str(self.parent.pk),
                SBADMIN_PARENT_INSTANCE_LABEL_VAR: str(self.parent),
            },
        )
        request.request_data = SimpleNamespace(
            configuration=SimpleNamespace(
                autocomplete_show_related_buttons=lambda *args, **kwargs: False,
            ),
            request_post={},
        )
        SBAdminThreadLocalService.set_request(request)
        return request

    def _widget(self):
        widget = SBAdminAutocompleteWidget(
            form_field=SimpleNamespace(
                empty_label="---------",
                error_messages={"invalid_choice": "bad"},
            ),
            model=Folder,
            multiselect=False,
            attrs={"id": "modal_folder_parent"},
        )
        widget.field_name = "parent"
        widget.form = SimpleNamespace(errors={})
        return widget

    def test_parent_instance_is_selected_when_widget_matches_request_field(self):
        self._request()

        context = self._widget().get_context("parent", None, {})

        self.assertEqual(
            json.loads(context["widget"]["value"]),
            [{"value": str(self.parent.pk), "label": str(self.parent)}],
        )
        self.assertEqual(
            context["widget"]["value_list"],
            [{"value": str(self.parent.pk), "label": str(self.parent)}],
        )
        self.assertNotIn("preselect_field", context["widget"]["attrs"])

    def test_parent_instance_is_ignored_when_widget_does_not_match_request_field(self):
        self._request(parent_field="modal_folder_other")

        context = self._widget().get_context("parent", None, {})

        self.assertNotIn("value", context["widget"])
        self.assertNotIn("value_list", context["widget"])

    def test_parent_instance_does_not_override_existing_value(self):
        self._request()
        existing_value = json.dumps(
            [{"value": str(self.existing.pk), "label": str(self.existing)}]
        )

        context = self._widget().get_context("parent", existing_value, {})

        self.assertEqual(
            json.loads(context["widget"]["value"]),
            [{"value": self.existing.pk, "label": str(self.existing)}],
        )
