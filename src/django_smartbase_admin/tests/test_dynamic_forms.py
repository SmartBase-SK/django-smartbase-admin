from django import forms
from django.contrib.admin.helpers import AdminForm
from django.http import QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminBaseFormInit
from django_smartbase_admin.engine.dynamic_forms import (
    SBADMIN_DYNAMIC_REGION_PARAM,
    SBDynamicRegion,
    SBInactiveFieldPolicy,
)
from django_smartbase_admin.engine.modal_view import ActionModalView
from django_smartbase_admin.templatetags.sb_admin_tags import (
    get_item,
    sbadmin_fieldset_context,
)


class DynamicRegionForm(SBAdminBaseFormInit, forms.Form):
    mode = forms.ChoiceField(
        choices=(
            ("physical", "Physical"),
            ("digital", "Digital"),
        ),
        initial="physical",
    )
    weight = forms.DecimalField(required=True)
    download_url = forms.URLField(required=True)
    billing_period = forms.ChoiceField(
        required=False,
        choices=(
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
        ),
    )

    class Meta:
        fieldsets = (
            (None, {"fields": ("mode",)}),
            (
                "Details",
                {
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="details",
                            trigger_fields=("mode",),
                            fields=("weight", "download_url", "billing_period"),
                            get_active_fields=lambda form, request, region: (
                                (("download_url", "billing_period"),)
                                if form.value_from_data_or_initial("mode") == "digital"
                                else ("weight",)
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.IGNORE,
                        ),
                    ),
                },
            ),
        )


class ClearInactiveRegionForm(SBAdminBaseFormInit, forms.Form):
    mode = forms.ChoiceField(
        choices=(
            ("a", "A"),
            ("b", "B"),
        ),
        initial="a",
    )
    field_a = forms.CharField(required=True)
    field_b = forms.CharField(required=True)

    class Meta:
        fieldsets = (
            (
                None,
                {
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="clearable",
                            trigger_fields=("mode",),
                            fields=("field_a", "field_b"),
                            get_active_fields=lambda form, request, region: (
                                ("field_b",)
                                if form.value_from_data_or_initial("mode") == "b"
                                else ("field_a",)
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.CLEAR,
                        ),
                    ),
                },
            ),
        )


class ChoiceSwitchRegionForm(SBAdminBaseFormInit, forms.Form):
    category = forms.ChoiceField(
        choices=(
            ("letters", "Letters"),
            ("numbers", "Numbers"),
        ),
        initial="letters",
    )
    value = forms.ChoiceField(required=False)

    class Meta:
        fieldsets = (
            (
                None,
                {
                    "fields": ("category",),
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="same_field_choices",
                            trigger_fields=("category",),
                            fields=("value",),
                            get_active_fields=lambda form, request, region: ("value",),
                        ),
                    ),
                },
            ),
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.value_from_data_or_initial("category") == "numbers":
            self.fields["value"].choices = (("1", "One"), ("2", "Two"))
        else:
            self.fields["value"].choices = (("a", "A"), ("b", "B"))

        self.prepare_dynamic_regions(kwargs.get("request"))


class DynamicRegionTriggerWidget(forms.TextInput):
    sb_admin_widget = True
    dynamic_region_trigger_event = "SBAutocompleteChange"

    def __init__(self, form_field=None, attrs=None):
        super().__init__(attrs=attrs)
        self.form_field = form_field


class DynamicRegionCustomTriggerForm(SBAdminBaseFormInit, forms.Form):
    address = forms.CharField(widget=DynamicRegionTriggerWidget)
    payload = forms.CharField(required=False)

    class Meta:
        fieldsets = (
            (
                None,
                {
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="payload",
                            trigger_fields=("address",),
                            fields=("payload",),
                        ),
                    ),
                },
            ),
        )


class CombinedDynamicFieldsetForm(SBAdminBaseFormInit, forms.Form):
    mode = forms.ChoiceField(
        choices=(
            ("physical", "Physical"),
            ("digital", "Digital"),
        ),
        initial="physical",
    )
    weight = forms.DecimalField(required=True)
    download_url = forms.URLField(required=True)

    class Meta:
        fieldsets = (
            (
                _("Combined details"),
                {
                    "fields": ("mode",),
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="combined_details",
                            trigger_fields=("mode",),
                            fields=("weight", "download_url"),
                            get_active_fields=lambda form, request, region: (
                                ("download_url",)
                                if form.value_from_data_or_initial("mode") == "digital"
                                else ("weight",)
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.IGNORE,
                        ),
                    ),
                },
            ),
        )


class CrossFieldsetRegionForm(SBAdminBaseFormInit, forms.Form):
    mode = forms.ChoiceField(
        choices=(
            ("basic", "Basic"),
            ("full", "Full"),
        ),
        initial="basic",
    )
    primary = forms.CharField(required=False)
    secondary = forms.CharField(required=False)

    class Meta:
        fieldsets = (
            (
                _("Primary"),
                {
                    "fields": ("mode",),
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="primary_region",
                            trigger_fields=("mode",),
                            fields=("primary",),
                            get_active_fields=lambda form, request, region: (
                                "primary",
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.PRESERVE,
                        ),
                    ),
                },
            ),
            (
                _("Secondary"),
                {
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="secondary_region",
                            trigger_fields=("mode",),
                            fields=("secondary",),
                            get_active_fields=lambda form, request, region: (
                                ("secondary",)
                                if form.value_from_data_or_initial("mode") == "full"
                                else ()
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.CLEAR,
                        ),
                    ),
                },
            ),
        )


class FakeView:
    def get_action_url(self, action, modifier="template"):
        return f"/sb-admin/{action}/{modifier}"


class FormWithExternalViewRegions(SBAdminBaseFormInit, forms.Form):
    message = forms.CharField()


class ViewWithFormSpecificRegion:
    def get_sbadmin_fieldsets(self, request, object_id):
        return (
            (
                None,
                {
                    "dynamic_regions": (
                        SBDynamicRegion(
                            name="sender_address",
                            fields=("sender_name",),
                            is_visible=lambda form, request, region: form.is_return_package,
                            get_active_fields=(
                                lambda form, request, region: form.sender_address_region_fields()
                            ),
                        ),
                    ),
                },
            ),
        )


class ExternalRegionActionModal(ActionModalView):
    form_class = FormWithExternalViewRegions


class DynamicRegionActionModal(ActionModalView):
    form_class = DynamicRegionForm


class DynamicFormTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/dynamic-form/")

    def test_value_from_data_or_initial_uses_prefixed_bound_data(self):
        form = DynamicRegionForm(
            data={
                "demo-mode": "digital",
                "demo-download_url": "https://example.com/file",
                "demo-billing_period": "monthly",
            },
            prefix="demo",
            request=self.request,
        )

        self.assertEqual(form.value_from_data_or_initial("mode"), "digital")
        self.assertEqual(
            form.value_from_data_or_initial("download_url"),
            "https://example.com/file",
        )

    def test_action_modal_form_does_not_use_parent_view_dynamic_regions(self):
        modal = ExternalRegionActionModal(
            view=ViewWithFormSpecificRegion(),
        )
        form = modal.get_form_class()(request=self.request)

        self.assertIsInstance(form.view, ViewWithFormSpecificRegion)
        self.assertEqual(form.get_dynamic_regions(self.request), ())

    def test_action_modal_dynamic_regions_use_current_request_path(self):
        request = RequestFactory().get("/modal/action/")
        modal = DynamicRegionActionModal(view=FakeView())
        form = modal.get_form_class()(request=request)

        self.assertEqual(form.fields["mode"].widget.attrs["hx-get"], "/modal/action/")

    def test_ignore_policy_skips_inactive_field_validation(self):
        form = DynamicRegionForm(
            data={
                "mode": "digital",
                "download_url": "https://example.com/file",
                "billing_period": "monthly",
                "weight": "",
            },
            request=self.request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn("weight", form.fields)
        self.assertNotIn("weight", form.cleaned_data)

    def test_clear_policy_clears_inactive_bound_data(self):
        form = ClearInactiveRegionForm(
            data={
                "mode": "a",
                "field_a": "visible",
                "field_b": "stale",
            },
            request=self.request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["field_a"], "visible")
        self.assertEqual(form.cleaned_data["field_b"], "")

    def test_region_binds_htmx_defaults_to_trigger_fields(self):
        class ViewBackedForm(DynamicRegionForm):
            view = FakeView()

        form = ViewBackedForm(request=self.request)
        attrs = form.fields["mode"].widget.attrs

        self.assertEqual(attrs["hx-get"], "/sb-admin/sbadmin_dynamic_region/add")
        self.assertEqual(attrs["hx-target"], "#sbadmin-dynamic-region-details")
        self.assertEqual(attrs["hx-include"], "closest form")
        self.assertEqual(attrs["hx-swap"], "outerHTML")
        self.assertIn(SBADMIN_DYNAMIC_REGION_PARAM, attrs["hx-vals"])

    def test_region_uses_widget_dynamic_trigger_event(self):
        class ViewBackedForm(DynamicRegionCustomTriggerForm):
            view = FakeView()

        form = ViewBackedForm(request=self.request)

        self.assertEqual(
            form.fields["address"].widget.attrs["hx-trigger"],
            "SBAutocompleteChange",
        )

    def test_dynamic_region_template_renders_only_active_fields(self):
        form = DynamicRegionForm(
            data={
                "mode": "digital",
                "download_url": "https://example.com/file",
                "billing_period": "monthly",
            },
            request=self.request,
        )
        region = form.get_dynamic_region("details", self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {"form": form, "region": region},
            request=self.request,
        )

        self.assertIn('id="sbadmin-dynamic-region-details"', html)
        self.assertIn('name="download_url"', html)
        self.assertIn('name="billing_period"', html)
        self.assertNotIn('name="weight"', html)

    def test_region_fields_must_be_flat_ownership_list(self):
        with self.assertRaises(TypeError):
            SBDynamicRegion(
                name="invalid",
                fields=(("first_name", "last_name"),),
            )

    def test_active_fields_can_define_grouped_layout(self):
        form = DynamicRegionForm(
            data={
                "mode": "digital",
                "download_url": "https://example.com/file",
                "billing_period": "monthly",
            },
            request=self.request,
        )
        region = form.get_dynamic_region("details", self.request)
        state = form.get_dynamic_region_state(region, self.request)

        self.assertEqual(state.active_field_names, ("download_url", "billing_period"))
        self.assertEqual(state.active_fields, (("download_url", "billing_period"),))

    def test_region_can_refresh_choices_for_the_same_field(self):
        form = ChoiceSwitchRegionForm(
            data={"category": "numbers", "value": "2"},
            request=self.request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields["value"].choices, [("1", "One"), ("2", "Two")])
        self.assertEqual(form.cleaned_data["value"], "2")

    def test_dynamic_region_fragment_renders_unbound_stale_choice_initial(self):
        form = ChoiceSwitchRegionForm(
            initial={"category": "letters", "value": "1"},
            request=self.request,
        )
        region = form.get_dynamic_region("same_field_choices", self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {
                "form": form,
                "region": region,
                "sbadmin_dynamic_region_fragment": True,
            },
            request=self.request,
        )

        self.assertFalse(form.is_bound)
        self.assertEqual(form.errors, {})
        self.assertIn('name="value"', html)
        self.assertNotIn("Select a valid choice", html)
        self.assertNotIn("valid choice", html)

    def test_dynamic_region_initial_is_built_from_request_data(self):
        data = QueryDict("category=letters&value=1")

        initial = SBAdmin._dynamic_region_initial_from_data(
            ChoiceSwitchRegionForm,
            data,
            None,
        )

        self.assertEqual(initial, {"category": "letters", "value": "1"})

    def test_admin_form_can_include_inactive_region_fields(self):
        form = DynamicRegionForm(request=self.request)
        fieldsets = [
            (fieldset.name, {"fields": fieldset.fields, "classes": fieldset.classes})
            for fieldset in form.fieldsets()
        ]

        admin_form = AdminForm(
            form,
            fieldsets,
            prepopulated_fields={},
            readonly_fields=[],
        )

        field_names = [
            field.field.name
            for fieldset in admin_form
            for line in fieldset
            for field in line
            if field.field.name
        ]
        self.assertIn("download_url", field_names)

    def test_fieldset_context_lookup_handles_lazy_translated_titles(self):
        lazy_title = _("Translated title")
        fieldsets_context = {lazy_title: {"dynamic_regions": ("region",)}}
        fieldset = type(
            "FieldsetStub", (), {"name": str(lazy_title), "sbadmin_context": None}
        )()

        self.assertEqual(
            get_item(fieldsets_context, str(lazy_title)),
            {"dynamic_regions": ("region",)},
        )
        self.assertEqual(
            sbadmin_fieldset_context(fieldsets_context, fieldset),
            {"dynamic_regions": ("region",)},
        )

    def test_dynamic_admin_fieldset_renders_trigger_and_target_wrapper(self):
        class ViewBackedForm(CombinedDynamicFieldsetForm):
            view = FakeView()

        form = ViewBackedForm(request=self.request)
        fieldsets = [
            (fieldset.name, {"fields": fieldset.fields, "classes": fieldset.classes})
            for fieldset in form.fieldsets()
        ]
        admin_form = AdminForm(
            form,
            fieldsets,
            prepopulated_fields={},
            readonly_fields=[],
        )

        html = render_to_string(
            "sb_admin/includes/fieldset.html",
            {
                "adminform": admin_form,
                "fieldset": next(iter(admin_form)),
                "fieldsets_context": form.get_fieldsets_context(),
            },
            request=self.request,
        )

        self.assertIn('name="mode"', html)
        self.assertIn('id="sbadmin-dynamic-region-combined-details"', html)
        self.assertIn('hx-target="#sbadmin-dynamic-region-combined-details"', html)
        self.assertIn(
            'hx-indicator="#sbadmin-dynamic-region-combined-details-loading"', html
        )
        self.assertIn('id="sbadmin-dynamic-region-combined-details-loading"', html)
        self.assertIn("page-loading", html)
        self.assertNotIn("htmx-indicator", html)
        self.assertIn('name="weight"', html)
        self.assertNotIn('name="download_url"', html)

    def test_dynamic_region_template_can_render_oob_swap(self):
        form = CombinedDynamicFieldsetForm(request=self.request)
        region = form.get_dynamic_region("combined_details", self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {
                "form": form,
                "region": region,
                "sbadmin_dynamic_region_oob": True,
            },
            request=self.request,
        )

        self.assertIn('hx-swap-oob="outerHTML"', html)

    def test_dynamic_region_fragment_does_not_render_loader(self):
        form = CombinedDynamicFieldsetForm(request=self.request)
        region = form.get_dynamic_region("combined_details", self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {
                "form": form,
                "region": region,
                "sbadmin_dynamic_region_fragment": True,
            },
            request=self.request,
        )

        self.assertIn('id="sbadmin-dynamic-region-combined-details"', html)
        self.assertNotIn('id="sbadmin-dynamic-region-combined-details-loading"', html)
        self.assertNotIn("page-loading", html)

    def test_same_trigger_can_target_regions_in_different_fieldsets(self):
        class ViewBackedForm(CrossFieldsetRegionForm):
            view = FakeView()

        form = ViewBackedForm(request=self.request)
        fieldsets = [
            (fieldset.name, {"fields": fieldset.fields, "classes": fieldset.classes})
            for fieldset in form.fieldsets()
        ]
        admin_form = AdminForm(
            form,
            fieldsets,
            prepopulated_fields={},
            readonly_fields=[],
        )
        rendered_fieldsets = []
        for fieldset in admin_form:
            rendered_fieldsets.append(
                render_to_string(
                    "sb_admin/includes/fieldset.html",
                    {
                        "adminform": admin_form,
                        "fieldset": fieldset,
                        "fieldsets_context": form.get_fieldsets_context(),
                    },
                    request=self.request,
                )
            )
        html = "".join(rendered_fieldsets)

        self.assertIn('name="mode"', html)
        self.assertIn('hx-target="#sbadmin-dynamic-region-primary-region"', html)
        self.assertIn(
            'hx-indicator="#sbadmin-dynamic-region-primary-region-loading"', html
        )
        self.assertIn('id="sbadmin-dynamic-region-primary-region"', html)
        self.assertIn('id="sbadmin-dynamic-region-primary-region-loading"', html)
        self.assertIn("page-loading", html)
        self.assertNotIn("htmx-indicator", html)
        self.assertIn('id="sbadmin-dynamic-region-secondary-region"', html)
        self.assertIn('id="sbadmin-dynamic-region-secondary-region-loading"', html)
