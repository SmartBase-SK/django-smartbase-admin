import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from filer.models import Folder

from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget


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
