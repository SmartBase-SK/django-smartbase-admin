import json

from django import forms
from django.contrib.admin.helpers import AdminForm
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import models
from django.http import QueryDict
from django.urls import path
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.admin.admin_base import (
    SBAdmin,
    SBAdminBaseForm,
    SBAdminBaseFormInit,
    SBAdminStackedInline,
)
from django_smartbase_admin.admin.widgets import SBAdminHiddenWidget
from django_smartbase_admin.engine.dynamic_forms import (
    SBADMIN_DYNAMIC_REGION_PARAM,
    SBADMIN_DYNAMIC_REGION_PREFIX_PARAM,
    SBAdminDynamicFormMixin,
    SBDynamicRegion,
    SBInactiveFieldPolicy,
)
from django_smartbase_admin.engine.modal_view import ActionModalView, RowActionModalView
from django_smartbase_admin.services.thread_local import (
    SBAdminThreadLocalService,
    sb_admin_request,
)
from django_smartbase_admin.templatetags.sb_admin_tags import get_tabular_context


dynamic_region_admin_site = AdminSite(name="admin")


class DynamicRegionDemoModel(models.Model):
    username = models.CharField(max_length=150)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class DynamicRegionInlineParent(models.Model):
    title = models.CharField(max_length=150)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class DynamicRegionInlineChild(models.Model):
    parent = models.ForeignKey(DynamicRegionInlineParent, on_delete=models.CASCADE)
    mode = models.CharField(
        max_length=20,
        choices=(
            ("basic", "Basic"),
            ("advanced", "Advanced"),
        ),
        default="basic",
    )
    summary = models.CharField(max_length=150, blank=True)
    notes = models.CharField(max_length=150, blank=True)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class DynamicRegionTestConfiguration:
    def get_form_field_widget_class(self, view, request, form_field, db_field, default):
        if db_field and db_field.name == "parent":
            return SBAdminHiddenWidget
        return default

    def apply_global_filter_to_queryset(self, qs, *args, **kwargs):
        return qs

    def restrict_queryset(self, qs, *args, **kwargs):
        return qs

    def has_permission(self, *args, **kwargs):
        return True


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
        sbadmin_fieldsets = (
            (None, {"fields": ("mode",)}),
            (
                "Details",
                {
                    "fields": (
                        SBDynamicRegion(
                            name="details",
                            trigger_fields=("mode",),
                            fields=("weight", "download_url", "billing_period"),
                            get_active_fields=lambda form, request, region: (
                                (("download_url", "billing_period"),)
                                if form["mode"].value() == "digital"
                                else ("weight",)
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.PRESERVE,
                        ),
                    ),
                },
            ),
        )


class MetaFieldsetsForm(SBAdminBaseFormInit, forms.Form):
    sbadmin_standalone_dynamic_regions = True

    title = forms.CharField()
    subtitle = forms.CharField(required=False)

    class Meta:
        fieldsets = (
            (
                "Content",
                {
                    "fields": ("title", "subtitle"),
                    "classes": ("wide",),
                    "description": "Editorial fields",
                },
            ),
        )


class MetaFieldsetsWithSBAdminOverrideForm(SBAdminBaseFormInit, forms.Form):
    sbadmin_standalone_dynamic_regions = True

    title = forms.CharField()
    subtitle = forms.CharField(required=False)

    class Meta:
        fieldsets = (
            (
                "Django",
                {
                    "fields": ("title",),
                },
            ),
        )
        sbadmin_fieldsets = (
            (
                "SBAdmin",
                {
                    "fields": ("subtitle",),
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
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        SBDynamicRegion(
                            name="clearable",
                            trigger_fields=("mode",),
                            fields=("field_a", "field_b"),
                            get_active_fields=lambda form, request, region: (
                                ("field_b",)
                                if form["mode"].value() == "b"
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
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        "category",
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
        if self["category"].value() == "numbers":
            self.fields["value"].choices = (("1", "One"), ("2", "Two"))
        else:
            self.fields["value"].choices = (("a", "A"), ("b", "B"))


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
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
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
    note = forms.CharField(required=False)

    class Meta:
        sbadmin_fieldsets = (
            (
                _("Combined details"),
                {
                    "fields": (
                        ("mode",),
                        SBDynamicRegion(
                            name="combined_details",
                            trigger_fields=("mode",),
                            fields=("weight", "download_url"),
                            get_active_fields=lambda form, request, region: (
                                ("download_url",)
                                if form["mode"].value() == "digital"
                                else ("weight",)
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.PRESERVE,
                        ),
                        ("note",),
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
        sbadmin_fieldsets = (
            (
                _("Primary"),
                {
                    "fields": (
                        "mode",
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
                    "fields": (
                        SBDynamicRegion(
                            name="secondary_region",
                            trigger_fields=("mode",),
                            fields=("secondary",),
                            get_active_fields=lambda form, request, region: (
                                ("secondary",) if form["mode"].value() == "full" else ()
                            ),
                            inactive_field_policy=SBInactiveFieldPolicy.CLEAR,
                        ),
                    ),
                },
            ),
        )


class GroupedRegionIgnoredForm(SBAdminBaseFormInit, forms.Form):
    mode = forms.CharField(required=False)
    visible = forms.CharField(required=False)
    ignored_a = forms.CharField(required=False)
    ignored_b = forms.CharField(required=False)

    class Meta:
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        (
                            "mode",
                            SBDynamicRegion(name="ignored_a", fields=("ignored_a",)),
                            SBDynamicRegion(name="ignored_b", fields=("ignored_b",)),
                        ),
                        SBDynamicRegion(name="visible", fields=("visible",)),
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
                    "fields": (
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


class CrossFieldsetDynamicRegionModal(ActionModalView):
    form_class = CrossFieldsetRegionForm


class RowObjectDynamicRegionForm(SBAdminBaseForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        "first_name",
                        SBDynamicRegion(
                            name="row_details",
                            trigger_fields=("first_name",),
                            fields=("last_name", "email"),
                            get_active_fields=lambda form, request, region: (
                                ("email",)
                                if form["first_name"].value() == "Digital"
                                else ("last_name",)
                            ),
                        ),
                    ),
                },
            ),
        )


class RowObjectDynamicRegionModal(RowActionModalView):
    form_class = RowObjectDynamicRegionForm

    def get_object(self):
        return User(first_name="Digital", last_name="Hidden")


class AdminFieldsetsDynamicRegionAdmin(SBAdmin):
    sbadmin_tabs = {"Profile": ("Profile",)}
    sbadmin_fieldsets = (
        (
            "Profile",
            {
                "fields": (
                    "username",
                    SBDynamicRegion(
                        name="profile",
                        trigger_fields=("username",),
                        fields=("first_name", "last_name"),
                        get_active_fields=lambda form, request, region: (
                            ("last_name",)
                            if form["username"].value() == "company"
                            else ("first_name",)
                        ),
                    ),
                ),
            },
        ),
    )

    def get_action_url(self, action, modifier="template"):
        return (
            "/admin/django_smartbase_admin/dynamicregiondemomodel/"
            f"{action}/{modifier}/"
        )

    def get_global_context(self, request, object_id=None):
        return {
            "admin_title": "Test admin",
            "const": {},
            "request_data": type(
                "RequestData",
                (),
                {
                    "menu_items": (),
                    "global_filter_instance": None,
                },
            )(),
            "username_data": {
                "full_name": "Test user",
                "initials": "TU",
            },
            "user_config": type("UserConfig", (), {"color_scheme": "light"})(),
            "view_id": self.get_id(),
        }

    def has_add_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


class DynamicRegionStackedInline(SBAdminStackedInline):
    model = DynamicRegionInlineChild
    extra = 1
    max_num = 1
    sbadmin_fieldsets = (
        (
            "Inline details",
            {
                "fields": (
                    "mode",
                    SBDynamicRegion(
                        name="inline_details",
                        trigger_fields=("mode",),
                        fields=("summary", "notes"),
                        get_active_fields=lambda form, request, region: (
                            ("notes",)
                            if form["mode"].value() == "advanced"
                            else ("summary",)
                        ),
                    ),
                ),
            },
        ),
    )

    def get_action_url(self, action, modifier="template"):
        return (
            "/admin/django_smartbase_admin/dynamicregioninlineparent/"
            f"inline/{action}/{modifier}/"
        )

    def has_add_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_view_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True


class InlineDynamicRegionParentAdmin(AdminFieldsetsDynamicRegionAdmin):
    sbadmin_tabs = {"Parent": ("Parent", DynamicRegionStackedInline)}
    inlines = (DynamicRegionStackedInline,)
    sbadmin_fieldsets = (
        (
            "Parent",
            {
                "fields": ("title",),
            },
        ),
    )

    def get_action_url(self, action, modifier="template"):
        return (
            "/admin/django_smartbase_admin/dynamicregioninlineparent/"
            f"{action}/{modifier}/"
        )


dynamic_region_admin_site.register(
    DynamicRegionDemoModel, AdminFieldsetsDynamicRegionAdmin
)
dynamic_region_admin_site.register(
    DynamicRegionInlineParent, InlineDynamicRegionParentAdmin
)
urlpatterns = [
    path("admin/", dynamic_region_admin_site.urls),
]


class DynamicFormTests(SimpleTestCase):
    databases = {"default"}

    def setUp(self):
        self.request = RequestFactory().get("/dynamic-form/")
        self.request_token = sb_admin_request.set(self.request)

    def tearDown(self):
        sb_admin_request.reset(self.request_token)

    def test_form_fieldsets_can_use_meta_fieldsets(self):
        form = MetaFieldsetsForm(request=self.request)
        fieldsets = list(form.fieldsets())

        self.assertEqual(form.get_sbadmin_fieldsets(), MetaFieldsetsForm.Meta.fieldsets)
        self.assertEqual(len(fieldsets), 1)
        self.assertEqual(fieldsets[0].name, "Content")
        self.assertEqual(fieldsets[0].fields, ("title", "subtitle"))
        self.assertEqual(fieldsets[0].classes, "wide")
        self.assertEqual(fieldsets[0].description, "Editorial fields")

    def test_form_fieldsets_prefers_meta_sbadmin_fieldsets(self):
        form = MetaFieldsetsWithSBAdminOverrideForm(request=self.request)
        fieldsets = list(form.fieldsets())

        self.assertEqual(
            form.get_sbadmin_fieldsets(),
            MetaFieldsetsWithSBAdminOverrideForm.Meta.sbadmin_fieldsets,
        )
        self.assertEqual(len(fieldsets), 1)
        self.assertEqual(fieldsets[0].name, "SBAdmin")
        self.assertEqual(fieldsets[0].fields, ("subtitle",))

    def test_action_modal_form_does_not_use_parent_view_dynamic_regions(self):
        modal = ExternalRegionActionModal(
            view=ViewWithFormSpecificRegion(),
        )
        form = modal.get_form_class()(request=self.request)

        self.assertIsInstance(form.view, ViewWithFormSpecificRegion)
        self.assertEqual(form.get_dynamic_regions(self.request), ())

    def test_action_modal_dynamic_regions_use_current_request_path(self):
        request = RequestFactory().get("/modal/action/")
        SBAdminThreadLocalService.set_request(request)
        modal = DynamicRegionActionModal(view=FakeView())
        form = modal.get_form_class()(request=request)

        self.assertEqual(form.fields["mode"].widget.attrs["hx-get"], "/modal/action/")

    def test_action_modal_dynamic_region_initial_is_built_from_request_data(self):
        request = RequestFactory().get(
            "/modal/action/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "details",
                "mode": "digital",
            },
        )
        SBAdminThreadLocalService.set_request(request)
        modal = DynamicRegionActionModal(view=FakeView())
        modal.setup(request)

        response = modal.get(request)
        html = response.content.decode()

        self.assertIn('name="download_url"', html)
        self.assertIn('name="billing_period"', html)
        self.assertNotIn('name="weight"', html)

    def test_action_modal_dynamic_region_response_includes_related_regions(self):
        request = RequestFactory().get(
            "/modal/action/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "primary_region",
                "mode": "full",
            },
            HTTP_HX_TRIGGER_NAME="mode",
        )
        SBAdminThreadLocalService.set_request(request)
        modal = CrossFieldsetDynamicRegionModal(view=FakeView())
        modal.setup(request)

        response = modal.get(request)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="sbadmin-dynamic-region-primary-region"', html)
        self.assertIn('id="sbadmin-dynamic-region-secondary-region"', html)
        self.assertIn('name="primary"', html)
        self.assertIn('name="secondary"', html)
        self.assertEqual(html.count('hx-swap-oob="outerHTML"'), 2)

    def test_row_action_modal_dynamic_region_initial_uses_object(self):
        request = RequestFactory().get(
            "/modal/row/123/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "row_details",
            },
        )
        SBAdminThreadLocalService.set_request(request)
        modal = RowObjectDynamicRegionModal(view=FakeView())
        modal.setup(request, modifier="123")

        response = modal.get(request)
        html = response.content.decode()

        self.assertIn('name="email"', html)
        self.assertNotIn('name="last_name"', html)

    @override_settings(ROOT_URLCONF=__name__)
    def test_model_admin_fieldsets_dynamic_regions_render_add_view(self):
        model_admin = dynamic_region_admin_site._registry[DynamicRegionDemoModel]
        request = RequestFactory().get(
            "/admin/django_smartbase_admin/dynamicregiondemomodel/add/",
            HTTP_SEC_FETCH_SITE="same-origin",
            HTTP_SEC_FETCH_DEST="iframe",
        )
        request.user = User(username="test", is_staff=True, is_superuser=True)
        request_token = sb_admin_request.set(request)

        try:
            response = model_admin.add_view(request)
            response.render()
        finally:
            sb_admin_request.reset(request_token)

        adminform_fieldsets = list(response.context_data["adminform"])
        form_class = response.context_data["adminform"].form.__class__
        fieldset_context = adminform_fieldsets[0].form.get_fieldset_context(
            adminform_fieldsets[0],
            request,
        )
        fieldset_layout = fieldset_context["fieldset_layout"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [fieldset.name for fieldset in adminform_fieldsets], ["Profile"]
        )
        self.assertEqual(
            response.context_data["tabs_context"], {"Profile": ("Profile",)}
        )
        tabular_context = get_tabular_context(
            response.context_data["adminform"],
            response.context_data["inline_admin_formsets"],
            response.context_data["tabs_context"],
        )
        self.assertEqual(
            [item["type"] for item in tabular_context["context"]["Profile"]["content"]],
            ["fieldset"],
        )
        self.assertTrue(issubclass(form_class, SBAdminDynamicFormMixin))
        self.assertFalse(issubclass(form_class, SBAdminBaseFormInit))
        self.assertEqual(fieldset_layout[0]["fieldset"].fields, ("username",))
        self.assertEqual(
            fieldset_layout[1]["region"].state.wrapper_id,
            "sbadmin-dynamic-region-profile",
        )
        self.assertEqual(
            fieldset_layout[1]["region"].state.active_fields, ("first_name",)
        )

    @override_settings(ROOT_URLCONF=__name__)
    def test_stacked_inline_fieldsets_dynamic_regions_render_add_view(self):
        model_admin = dynamic_region_admin_site._registry[DynamicRegionInlineParent]
        request = RequestFactory().get(
            "/admin/django_smartbase_admin/dynamicregioninlineparent/add/",
            HTTP_SEC_FETCH_SITE="same-origin",
            HTTP_SEC_FETCH_DEST="iframe",
        )
        request.request_data = type(
            "RequestData",
            (),
            {
                "configuration": DynamicRegionTestConfiguration(),
                "global_filter_instance": None,
            },
        )()
        request.user = User(username="test", is_staff=True, is_superuser=True)
        request_token = sb_admin_request.set(request)

        try:
            response = model_admin.add_view(request)
            response.render()
        finally:
            sb_admin_request.reset(request_token)

        inline_admin_formsets = response.context_data["inline_admin_formsets"]
        inline_form = list(inline_admin_formsets[0])[0].form
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(issubclass(inline_form.__class__, SBAdminDynamicFormMixin))
        self.assertIn('data-sbadmin-dynamic-region="inline_details"', html)
        self.assertIn('hx-target="#sbadmin-dynamic-region-', html)
        self.assertIn('-0-summary"', html)
        self.assertNotIn('-0-notes"', html)

    @override_settings(ROOT_URLCONF=__name__)
    def test_stacked_inline_dynamic_region_fragment_uses_form_prefix(self):
        model_admin = dynamic_region_admin_site._registry[DynamicRegionInlineParent]
        request = RequestFactory().get(
            "/admin/django_smartbase_admin/dynamicregioninlineparent/inline/"
            "sbadmin_dynamic_region/add/",
            data={
                SBADMIN_DYNAMIC_REGION_PARAM: "inline_details",
                SBADMIN_DYNAMIC_REGION_PREFIX_PARAM: "children-0",
                "children-0-mode": "advanced",
            },
            HTTP_HX_TRIGGER_NAME="children-0-mode",
        )
        request.request_data = type(
            "RequestData",
            (),
            {
                "configuration": DynamicRegionTestConfiguration(),
                "global_filter_instance": None,
            },
        )()
        request.user = User(username="test", is_staff=True, is_superuser=True)
        request_token = sb_admin_request.set(request)

        try:
            inline = model_admin.get_inline_instances(request, None)[0]
            response = inline.sbadmin_dynamic_region(request, "add")
        finally:
            sb_admin_request.reset(request_token)

        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'id="sbadmin-dynamic-region-children-0-inline-details"',
            html,
        )
        self.assertIn('name="children-0-notes"', html)
        self.assertNotIn('name="children-0-summary"', html)

    def test_preserve_policy_skips_inactive_field_validation(self):
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

    def test_clear_policy_uses_django_empty_values_for_inactive_bound_data(self):
        class TypedInactiveRegionForm(SBAdminBaseFormInit, forms.Form):
            sbadmin_standalone_dynamic_regions = True

            mode = forms.ChoiceField(choices=(("hide", "Hide"), ("show", "Show")))
            enabled = forms.BooleanField(required=False)
            colors = forms.MultipleChoiceField(
                required=False,
                choices=(("red", "Red"), ("blue", "Blue")),
            )
            starts_at = forms.SplitDateTimeField(required=False)

            class Meta:
                sbadmin_fieldsets = (
                    (
                        None,
                        {
                            "fields": (
                                "mode",
                                SBDynamicRegion(
                                    name="typed_fields",
                                    trigger_fields=("mode",),
                                    fields=("enabled", "colors", "starts_at"),
                                    get_active_fields=(
                                        lambda form, request, region: (
                                            ("enabled", "colors", "starts_at")
                                            if form["mode"].value() == "show"
                                            else ()
                                        )
                                    ),
                                    inactive_field_policy=SBInactiveFieldPolicy.CLEAR,
                                ),
                            ),
                        },
                    ),
                )

        form = TypedInactiveRegionForm(
            data=QueryDict(
                "mode=hide&enabled=on&colors=red"
                "&starts_at_0=2026-05-18&starts_at_1=09%3A30%3A00"
            ),
            request=self.request,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data["enabled"], False)
        self.assertEqual(form.cleaned_data["colors"], [])
        self.assertIsNone(form.cleaned_data["starts_at"])

    def test_region_binds_htmx_defaults_to_trigger_fields(self):
        class ViewBackedForm(DynamicRegionForm):
            view = FakeView()

        form = ViewBackedForm(request=self.request)
        attrs = form.fields["mode"].widget.attrs

        self.assertEqual(attrs["hx-get"], "/sb-admin/sbadmin_dynamic_region/add")
        self.assertEqual(attrs["hx-target"], "#sbadmin-dynamic-region-details")
        self.assertEqual(attrs["hx-include"], "closest form")
        self.assertEqual(attrs["hx-swap"], "none")
        hx_vals = json.loads(attrs["hx-vals"])
        self.assertEqual(hx_vals[SBADMIN_DYNAMIC_REGION_PARAM], "details")
        self.assertNotIn(SBADMIN_DYNAMIC_REGION_PREFIX_PARAM, hx_vals)

    def test_region_binds_form_prefix_only_when_present(self):
        class ViewBackedForm(DynamicRegionForm):
            view = FakeView()

        form = ViewBackedForm(prefix="children-0", request=self.request)
        attrs = form.fields["mode"].widget.attrs
        hx_vals = json.loads(attrs["hx-vals"])

        self.assertEqual(
            attrs["hx-target"],
            "#sbadmin-dynamic-region-children-0-details",
        )
        self.assertEqual(
            hx_vals[SBADMIN_DYNAMIC_REGION_PREFIX_PARAM],
            "children-0",
        )

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
            {"dynamic_region": form.get_dynamic_region_context(region, self.request)},
            request=self.request,
        )

        self.assertIn('id="sbadmin-dynamic-region-details"', html)
        self.assertIn('name="download_url"', html)
        self.assertIn('name="billing_period"', html)
        self.assertNotIn('name="weight"', html)

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

        self.assertEqual(
            state.active_field_names, frozenset({"download_url", "billing_period"})
        )
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
                "dynamic_region": form.get_dynamic_region_context(region, self.request),
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
            {},
        )

        self.assertEqual(initial, {"category": "letters", "value": "1"})

    def test_dynamic_region_initial_uses_widget_data_extraction(self):
        class WidgetValueForm(forms.Form):
            colors = forms.MultipleChoiceField(
                choices=(("red", "Red"), ("blue", "Blue"))
            )
            starts_at = forms.SplitDateTimeField()

        data = QueryDict(
            "colors=red&colors=blue&starts_at_0=2026-05-18&starts_at_1=09%3A30%3A00"
        )

        initial = SBAdmin._dynamic_region_initial_from_data(
            WidgetValueForm,
            data,
            {},
        )

        self.assertEqual(
            initial,
            {
                "colors": ["red", "blue"],
                "starts_at": ["2026-05-18", "09:30:00"],
            },
        )

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
        self.assertIn('name="note"', html)
        self.assertLess(
            html.index('name="mode"'),
            html.index('id="sbadmin-dynamic-region-combined-details"'),
        )
        self.assertLess(
            html.index('id="sbadmin-dynamic-region-combined-details"'),
            html.index('name="note"'),
        )

    def test_regions_inside_grouped_fields_are_ignored(self):
        form = GroupedRegionIgnoredForm(request=self.request)

        self.assertEqual(
            tuple(region.name for region in form.get_dynamic_regions(self.request)),
            ("visible",),
        )

    def test_dynamic_region_fragment_renders_oob_swap(self):
        form = CombinedDynamicFieldsetForm(request=self.request)
        region = form.get_dynamic_region("combined_details", self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {
                "dynamic_region": form.get_dynamic_region_context(region, self.request),
                "sbadmin_dynamic_region_fragment": True,
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
                "dynamic_region": form.get_dynamic_region_context(region, self.request),
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
