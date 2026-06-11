from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from django_smartbase_admin.admin.widgets import (
    SBAdminCopyableTextInputWidget,
    SBAdminTextInputWidget,
)


class CopyableWidgetTests(SimpleTestCase):
    def test_text_input_renders_suffix_icon_button(self):
        class ExampleForm(forms.Form):
            api_key = forms.CharField(label="API key", help_text="Keep this private.")

        form = ExampleForm(initial={"api_key": "psp_test"})
        form.fields["api_key"].widget = SBAdminTextInputWidget(
            form.fields["api_key"],
            attrs={"readonly": "readonly"},
            suffix_icon="Minus-the-top",
            suffix_button_attrs={
                "title": "Copy key",
                "aria-label": "Copy key",
                "data-sbadmin-copy-button": True,
                "data-sbadmin-copied-label": "Copied key",
            },
        )

        html = form["api_key"].as_widget()
        media = str(form.media)

        self.assertIn('value="psp_test"', html)
        self.assertIn('class="input rounded-r-none"', html)
        self.assertIn('class="input-affix input-affix--readonly"', html)
        self.assertIn("data-sbadmin-copy-button", html)
        self.assertIn('data-sbadmin-copied-label="Copied key"', html)
        self.assertIn('href="#Minus-the-top"', html)
        self.assertIn("Keep this private.", html)
        self.assertNotIn("copy_to_clipboard.js", media)

    def test_text_input_renders_prefix_icon_button(self):
        class ExampleForm(forms.Form):
            tracking_code = forms.CharField(label="Tracking code")

        form = ExampleForm(initial={"tracking_code": "TRACK-1"})
        form.fields["tracking_code"].widget = SBAdminTextInputWidget(
            form.fields["tracking_code"],
            prefix_icon="Search",
            prefix_button_attrs={
                "title": "Find",
                "aria-label": "Find",
                "data-find-tracking-code": True,
            },
        )

        html = form["tracking_code"].as_widget()

        self.assertIn('class="input rounded-l-none"', html)
        self.assertIn('class="input-affix"', html)
        self.assertNotIn("input-affix--readonly", html)
        self.assertIn("data-find-tracking-code", html)
        self.assertIn('href="#Search"', html)

    def test_copyable_text_input_uses_suffix_icon_button(self):
        class ExampleForm(forms.Form):
            api_key = forms.CharField(label="API key", help_text="Keep this private.")

        form = ExampleForm(initial={"api_key": "psp_test"})
        form.fields["api_key"].widget = SBAdminCopyableTextInputWidget(
            form.fields["api_key"],
            attrs={"readonly": "readonly"},
            copy_label="Copy key",
            copied_label="Copied key",
        )

        html = form["api_key"].as_widget()
        media = str(form.media)

        self.assertIn('value="psp_test"', html)
        self.assertIn('class="input rounded-r-none"', html)
        self.assertIn('class="input-affix input-affix--readonly"', html)
        self.assertIn("data-sbadmin-copy-button", html)
        self.assertIn('data-sbadmin-copy-label="Copy key"', html)
        self.assertIn('data-sbadmin-copied-label="Copied key"', html)
        self.assertIn('href="#Minus-the-top"', html)
        self.assertIn("Keep this private.", html)
        self.assertNotIn("copy_to_clipboard.js", media)

    def test_prefix_and_prefix_icon_are_mutually_exclusive(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "Use either prefix or prefix_icon, not both."
        ):
            SBAdminTextInputWidget(prefix="ID", prefix_icon="Search")

    def test_suffix_and_suffix_icon_are_mutually_exclusive(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "Use either suffix or suffix_icon, not both."
        ):
            SBAdminTextInputWidget(suffix="€", suffix_icon="Minus-the-top")
