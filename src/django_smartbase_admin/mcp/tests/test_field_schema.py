from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.test import SimpleTestCase

from django_smartbase_admin.admin.widgets import SBAdminReadOnlyPasswordHashWidget
from django_smartbase_admin.mcp.field_schema import field_info
from django_smartbase_admin.mcp.form_encoding import encode_form_components


class SecretFieldSchemaTests(SimpleTestCase):
    def test_normal_null_value_is_available(self):
        info = field_info(forms.CharField(required=False), None)

        self.assertIsNone(info["value"])
        self.assertTrue(info["value_available"])
        self.assertFalse(info["write_only"])
        self.assertFalse(info["readonly"])

    def test_password_input_is_write_only(self):
        field = forms.CharField(widget=forms.PasswordInput())

        info = field_info(field, "must-not-leak")

        self.assertIsNone(info["value"])
        self.assertFalse(info["value_available"])
        self.assertTrue(info["write_only"])
        self.assertFalse(info["readonly"])

    def test_custom_field_can_opt_in_to_write_only(self):
        field = forms.CharField()
        field.mcp_write_only = True

        info = field_info(field, "must-not-leak")

        self.assertIsNone(info["value"])
        self.assertFalse(info["value_available"])
        self.assertTrue(info["write_only"])

    def test_disabled_secret_field_is_readonly_and_unavailable(self):
        field = forms.CharField(disabled=True)
        field.widget.mcp_value_available = False

        info = field_info(field, "must-not-leak")

        self.assertIsNone(info["value"])
        self.assertFalse(info["value_available"])
        self.assertFalse(info["write_only"])
        self.assertTrue(info["readonly"])
        self.assertIsNone(info["widget"])

    def test_readonly_password_hash_widget_never_discloses_hash(self):
        field = ReadOnlyPasswordHashField()
        field.widget = SBAdminReadOnlyPasswordHashWidget(form_field=field)

        info = field_info(field, "must-not-leak")

        self.assertIsNone(info["value"])
        self.assertFalse(info["value_available"])
        self.assertFalse(info["write_only"])
        self.assertTrue(info["readonly"])

    def test_disabled_field_cannot_be_overridden(self):
        class DisabledFieldForm(forms.Form):
            secret = forms.CharField(disabled=True)

        with self.assertRaisesRegex(LookupError, "Cannot set form fields"):
            encode_form_components(
                {"main": DisabledFieldForm(initial={"secret": "hidden"})},
                {"main": {"secret": "replacement"}},
            )


class FormComponentEncodingTests(SimpleTestCase):
    def test_falsey_non_dictionary_component_values_are_rejected(self):
        components = {"main": forms.Form()}

        for invalid in (False, 0, "", []):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    TypeError, "component_values must be a dictionary"
                ):
                    encode_form_components(components, invalid)

    def test_falsey_non_dictionary_form_component_is_rejected(self):
        components = {"main": forms.Form()}

        for invalid in (False, 0, "", []):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    TypeError, "Form component 'main' must be a field dictionary"
                ):
                    encode_form_components(components, {"main": invalid})

    def test_none_still_means_no_values_supplied(self):
        component = forms.Form()

        self.assertEqual(encode_form_components({"main": component}, None), {})
        self.assertEqual(
            encode_form_components({"main": component}, {"main": None}), {}
        )
