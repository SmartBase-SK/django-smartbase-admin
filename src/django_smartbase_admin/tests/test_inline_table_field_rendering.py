from django import forms
from django.db import models
from django.template import Context, Template
from django.test import SimpleTestCase

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.monkeypatch.admin_readonly_field_monkeypatch import (
    SBAdminReadonlyField,
)


class InlineReadonlyDemoModel(models.Model):
    name = models.CharField(max_length=150, verbose_name="Name")
    enabled = models.BooleanField(default=False, verbose_name="Enabled")

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class LabelledWidgetMixin:
    def __init__(self, form_field):
        self.form_field = form_field
        super().__init__(attrs={"class": "input"})

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["form_field"] = self.form_field
        return context


class LabelledTextInput(LabelledWidgetMixin, forms.TextInput):
    template_name = "sb_admin/widgets/text.html"


class LabelledCheckboxInput(LabelledWidgetMixin, forms.CheckboxInput):
    template_name = "sb_admin/widgets/checkbox.html"


class InlineReadonlyDemoForm(forms.ModelForm):
    class Meta:
        model = InlineReadonlyDemoModel
        fields = ()


class InlineReadonlyDemoAdmin:
    admin_site = sb_admin_site
    all_base_fields_form = forms.Form

    def get_empty_value_display(self):
        return "-"


class InlineTableFieldRenderingTests(SimpleTestCase):
    def render_inline_table_field(self, form):
        template = Template(
            "{% load sb_admin_tags %}{% sb_admin_render_inline_table_field form.field %}"
        )
        return template.render(Context({"form": form}))

    def test_inline_table_field_hides_leading_widget_label(self):
        class ExampleForm(forms.Form):
            field = forms.CharField(label="Name")

        form = ExampleForm()
        form.fields["field"].widget = LabelledTextInput(form.fields["field"])

        html = self.render_inline_table_field(form)

        self.assertNotIn("<label", html)
        self.assertIn('type="text"', html)
        self.assertNotIn("sbadmin_hide_label", html)

    def test_inline_table_field_keeps_checkbox_label_after_input(self):
        class ExampleForm(forms.Form):
            field = forms.BooleanField(label="Enabled", required=False)

        form = ExampleForm()
        form.fields["field"].widget = LabelledCheckboxInput(form.fields["field"])

        html = self.render_inline_table_field(form)

        self.assertIn('type="checkbox"', html)
        self.assertIn("<label", html)
        self.assertIn("Enabled", html)
        self.assertNotIn("sbadmin_hide_label", html)

    def test_inline_table_readonly_field_hides_own_label(self):
        form = InlineReadonlyDemoForm(
            instance=InlineReadonlyDemoModel(name="Saved name")
        )
        readonly_field = SBAdminReadonlyField(
            form,
            "name",
            is_first=False,
            model_admin=InlineReadonlyDemoAdmin(),
        )

        html = readonly_field.contents(hide_label=True)

        self.assertIn("Saved name", html)
        self.assertNotIn("Name", html)

    def test_inline_table_readonly_boolean_keeps_control_label_only(self):
        form = InlineReadonlyDemoForm(instance=InlineReadonlyDemoModel(enabled=True))
        readonly_field = SBAdminReadonlyField(
            form,
            "enabled",
            is_first=False,
            model_admin=InlineReadonlyDemoAdmin(),
        )

        html = readonly_field.contents(hide_label=True)

        self.assertIn('type="checkbox"', html)
        self.assertIn("checked", html)
        self.assertNotIn(">Enabled<", html)
