import json
from types import SimpleNamespace
from unittest.mock import patch

from django import forms
from django.contrib.admin.helpers import AdminForm
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import models
from django.http import HttpResponse, JsonResponse, QueryDict
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.admin.admin_base import (
    SBAdmin,
    SBAdminBaseForm,
    SBAdminBaseFormInit,
    SBAdminStackedInline,
)
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.widgets import (
    SBAdminAutocompleteWidget,
    SBAdminHiddenWidget,
)
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminFormViewAction,
    SBAdminRowAction,
    sbadmin_action,
)
from django_smartbase_admin.engine.admin_base_view import SBAdminBaseView
from django_smartbase_admin.engine.const import (
    ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR,
    Action,
)
from django_smartbase_admin.engine.dynamic_forms import (
    SBADMIN_DYNAMIC_REGION_PARAM,
    SBADMIN_DYNAMIC_REGION_PREFIX_PARAM,
    SBAdminDynamicFormMixin,
    SBDynamicRegion,
    SBDynamicRegionSource,
    SBInactiveFieldPolicy,
)
from django_smartbase_admin.engine.modal_view import (
    ActionModalView,
    RowActionModalView,
    SBAdminStandaloneFormView,
)
from django_smartbase_admin.services.thread_local import (
    SBAdminThreadLocalService,
    sb_admin_request,
)
from django_smartbase_admin.services.views import SBAdminViewService
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
    sbadmin_dynamic_region_source = SBDynamicRegionSource.FORM

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
    sbadmin_dynamic_region_source = SBDynamicRegionSource.FORM

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
    def get_action_url(self, action, modifier="template", object_id=None):
        url = f"/sb-admin/{action}/{modifier}"
        if object_id is not None:
            url = f"{url}/{object_id}"
        return url


class FakeFieldsetActionView(SBAdminBaseView):
    def __init__(self, denied_action_id=None):
        self.denied_action_id = denied_action_id

    def get_action_url(self, action, modifier="template", object_id=None):
        url = f"/sb-admin/{action}/{modifier}"
        if object_id is not None:
            url = f"{url}/{object_id}"
        return url

    def has_permission_for_action(self, request, action):
        return getattr(action, "action_id", None) != self.denied_action_id


class ReadonlyDynamicRegionView(FakeView):
    admin_site = sb_admin_site

    def get_empty_value_display(self):
        return "-"

    def get_readonly_fields(self, request, obj=None):
        return ("readonly_summary",)

    def readonly_summary(self, obj):
        return f"Summary for {obj.username}"


ReadonlyDynamicRegionView.readonly_summary.short_description = "Summary"


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


class ReadonlyDynamicRegionForm(SBAdminBaseForm):
    view = ReadonlyDynamicRegionView()

    class Meta:
        model = DynamicRegionDemoModel
        fields = ("username",)
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        SBDynamicRegion(
                            name="readonly_details",
                            fields=("readonly_summary",),
                        ),
                    ),
                },
            ),
        )


class DeferredDynamicRegionForm(SBAdminBaseFormInit, forms.Form):
    view = FakeView()

    details = forms.CharField(required=False)

    class Meta:
        sbadmin_fieldsets = (
            (
                None,
                {
                    "fields": (
                        SBDynamicRegion(
                            name="lazy_details",
                            fields=("details",),
                            defer_trigger="load",
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


class DynamicRegionStandaloneView(SBAdminStandaloneFormView):
    form_class = DynamicRegionForm


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


class CompleteActionAutocompleteWidget(SBAdminAutocompleteWidget):
    def action_autocomplete(self, request, modifier, object_id=None):
        return JsonResponse(
            {
                "data": [
                    {
                        "source": self.form.source_name,
                        "field": self.field_name,
                        "view": self.view.get_id(),
                        "object_id": request.request_data.object_id,
                        "modifier": modifier,
                    }
                ]
            }
        )


class CompleteActionForm(SBAdminBaseFormInit, forms.Form):
    source_name = None
    lookup = forms.CharField(
        required=False,
        widget=CompleteActionAutocompleteWidget(model=User, multiselect=False),
    )

    def __init__(self, *args, source_name=None, **kwargs):
        self.source_name = source_name or self.source_name
        super().__init__(*args, **kwargs)


def complete_action_form_class(source_name):
    return type(
        f"Complete{source_name.title().replace('_', '')}ActionForm",
        (CompleteActionForm,),
        {"source_name": source_name, "__module__": __name__},
    )


class CompleteActionModal(ActionModalView):
    source_name = None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["source_name"] = self.source_name
        return kwargs

    def render_to_response(self, context, **response_kwargs):
        form = context["form"]
        return JsonResponse(
            {
                "source": form.source_name,
                "object_id": self.request.request_data.object_id,
                "autocomplete_ids": sorted(
                    self.request.request_data.autocomplete_map.keys()
                ),
            }
        )


def complete_action_modal_class(source_name):
    form_class = complete_action_form_class(source_name)
    return type(
        f"Complete{source_name.title().replace('_', '')}ActionModal",
        (CompleteActionModal,),
        {
            "source_name": source_name,
            "form_class": form_class,
            "__module__": __name__,
        },
    )


COMPLETE_ACTION_MODALS = {
    source_name: complete_action_modal_class(source_name)
    for source_name in (
        "list_selection",
        "list",
        "row",
        "detail",
        "fieldset",
        "inline",
    )
}


class CompleteUnrelatedActionForm(CompleteActionForm):
    source_name = "unrelated"


class CompleteUnrelatedActionModal(CompleteActionModal):
    source_name = "unrelated"
    form_class = CompleteUnrelatedActionForm

    def get_form_kwargs(self):
        raise AssertionError("Unrelated action form should not be initialized")


class CompleteActionRequestData(SimpleNamespace):
    def register_autocomplete_view(self, view):
        self.autocomplete_map[view.get_id()] = view


class CompleteActionConfiguration(DynamicRegionTestConfiguration):
    plugins = []
    default_list_sticky_header_and_footer = False


class CompleteActionSourceView(SBAdminBaseView):
    method_action_id = "complete_method_action"

    def get_id(self):
        return self.view_id

    def get_sub_views(self, configuration):
        return []

    def get_action_url(self, action, modifier="template", object_id=None):
        url = f"/sb-admin/{self.get_id()}/{action}/{modifier}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

    def has_view_or_change_permission(self, request, obj=None):
        return True

    def has_permission_for_action(self, request, action):
        return True

    @sbadmin_action(permission="view")
    def complete_method_action(self, request, modifier, object_id=None):
        return HttpResponse(f"method:{self.get_id()}:{modifier}:{object_id}")

    def target_action(self, source_name):
        return SBAdminFormViewAction(
            target_view=COMPLETE_ACTION_MODALS[source_name],
            title=f"{source_name} target",
            view=self,
            open_in_modal=True,
        )

    def method_action(self, source_name):
        return SBAdminCustomAction(
            title=f"{source_name} method",
            view=self,
            action_id=self.method_action_id,
        )

    def url_action(self, source_name):
        return SBAdminCustomAction(
            title=f"{source_name} url",
            url=f"/external/{source_name}/",
        )

    def unrelated_target_action(self, source_name):
        return SBAdminFormViewAction(
            target_view=CompleteUnrelatedActionModal,
            title=f"{source_name} unrelated",
            view=self,
            open_in_modal=True,
        )

    def actions_for(self, source_name):
        return (
            self.target_action(source_name),
            self.method_action(source_name),
            self.url_action(source_name),
            self.unrelated_target_action(source_name),
        )


class CompleteInlineActionView(CompleteActionSourceView):
    view_id = "complete_inline_actions"

    def get_sbadmin_inline_list_actions_processed(self, request):
        return self.process_inline_actions(request, self.actions_for("inline"))

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        super().init_view_dynamic(request, request_data, **kwargs)
        self.get_sbadmin_inline_list_actions_processed(request)
        self._register_action_autocomplete(request)

    def _register_action_autocomplete(self, request):
        self.register_action_autocomplete_views(
            request, self.get_sbadmin_inline_list_actions_processed(request)
        )


class CompleteParentActionView(CompleteActionSourceView):
    view_id = "complete_parent_actions"

    def get_sbadmin_list_display(self, request):
        return []

    def get_sbadmin_list_selection_actions(self, request):
        return self.actions_for("list_selection")

    def get_sbadmin_list_selection_actions_processed(self, request):
        return self.process_list_actions(
            request, self.get_sbadmin_list_selection_actions(request)
        )

    def get_sbadmin_list_actions(self, request):
        return self.actions_for("list")

    def get_sbadmin_list_actions_processed(self, request):
        return self.process_list_actions(
            request, self.get_sbadmin_list_actions(request)
        )

    def get_sbadmin_row_actions(self, request):
        target_action, method_action, url_action, unrelated_action = self.actions_for(
            "row"
        )
        return [
            SBAdminRowAction(
                title="row group",
                icon="Menu",
                sub_actions=[
                    SBAdminRowAction(
                        target_view=target_action.target_view,
                        title=target_action.title,
                        view=self,
                        icon="Search",
                    ),
                    SBAdminRowAction(
                        action_id=method_action.action_id,
                        title=method_action.title,
                        view=self,
                        icon="Edit",
                    ),
                    SBAdminRowAction(
                        url="/external/row/__object_id__/",
                        title=url_action.title,
                        icon="Open",
                    ),
                    SBAdminRowAction(
                        target_view=unrelated_action.target_view,
                        title=unrelated_action.title,
                        view=self,
                        icon="Warning",
                    ),
                ],
            ),
        ]

    def get_sbadmin_row_actions_processed(self, request):
        return self.process_row_actions(request, self.get_sbadmin_row_actions(request))

    def get_sbadmin_detail_actions(self, request, object_id=None):
        return self.actions_for("detail")

    def get_sbadmin_fieldsets(self, request, object_id=None):
        return (
            (
                "Main",
                {
                    "fields": (),
                    "actions": self.actions_for("fieldset"),
                },
            ),
        )

    def get_sbadmin_fieldset_actions(
        self, request, fieldset, fieldset_data, object_id=None
    ):
        return fieldset_data.get("actions")

    def init_view_dynamic(self, request, request_data=None, **kwargs):
        super().init_view_dynamic(request, request_data, **kwargs)
        self.get_sbadmin_list_selection_actions_processed(request)
        self.get_sbadmin_list_actions_processed(request)
        self.get_sbadmin_row_actions_processed(request)
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        if object_id is not None:
            self.get_sbadmin_detail_actions_processed(request, object_id)
            self.get_sbadmin_fieldsets_actions_processed(request, object_id)
        self._register_action_autocomplete(request)

    def _register_action_autocomplete(self, request):
        object_id = getattr(getattr(request, "request_data", None), "object_id", None)
        all_actions = [
            *self.get_sbadmin_list_selection_actions_processed(request),
            *self.get_sbadmin_list_actions_processed(request),
            *self.get_sbadmin_row_actions_processed(request),
        ]
        if object_id is not None:
            all_actions.extend(
                self.get_sbadmin_detail_actions_processed(request, object_id)
            )
            all_actions.extend(
                self.get_sbadmin_fieldsets_actions_processed(request, object_id)
            )
        self.register_action_autocomplete_views(request, all_actions)


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

    def get_action_url(self, action, modifier="template", object_id=None):
        url = (
            "/admin/django_smartbase_admin/dynamicregiondemomodel/"
            f"{action}/{modifier}/"
        )
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

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

    def get_action_url(self, action, modifier="template", object_id=None):
        url = (
            "/admin/django_smartbase_admin/dynamicregioninlineparent/"
            f"inline/{action}/{modifier}/"
        )
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

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

    def get_action_url(self, action, modifier="template", object_id=None):
        url = (
            "/admin/django_smartbase_admin/dynamicregioninlineparent/"
            f"{action}/{modifier}/"
        )
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url


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

    def render_fieldset(self, form, index=0):
        fieldsets = []
        for fieldset in form.fieldsets():
            fieldset_data = {
                "fields": fieldset.fields,
                "classes": fieldset.classes,
            }
            if fieldset.description:
                fieldset_data["description"] = fieldset.description
            fieldsets.append((fieldset.name, fieldset_data))
        admin_form = AdminForm(
            form,
            fieldsets,
            prepopulated_fields={},
            readonly_fields=[],
        )
        fieldset = list(admin_form)[index]
        return render_to_string(
            "sb_admin/includes/fieldset.html",
            {
                "adminform": admin_form,
                "fieldset": fieldset,
            },
            request=self.request,
        )

    def assert_collapse_body(self, html, collapse_id, *expected_classes):
        self.assertRegex(
            html,
            rf'id="{collapse_id}" class="[^"]*\bcollapse\b[^"]*"',
        )
        collapse_class = html.split(f'id="{collapse_id}" class="', 1)[1].split('"', 1)[
            0
        ]
        for expected_class in expected_classes:
            self.assertIn(expected_class, collapse_class.split())

    def assert_fieldset_hidden(self, html):
        self.assertIn('data-sbadmin-hide-if-empty="true"', html)
        fieldset_class = html.split('<fieldset class="', 1)[1].split('"', 1)[0]
        self.assertIn("hidden", fieldset_class.split())

    def assert_fieldset_visible(self, html):
        self.assertIn('data-sbadmin-hide-if-empty="true"', html)
        fieldset_class = html.split('<fieldset class="', 1)[1].split('"', 1)[0]
        self.assertNotIn("hidden", fieldset_class.split())

    def test_hide_if_empty_fieldset_keeps_non_empty_static_fieldset_visible(self):
        class NonEmptyFieldsetForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("title",),
                            "hide_if_empty": True,
                        },
                    ),
                )

        html = self.render_fieldset(NonEmptyFieldsetForm(request=self.request))

        self.assert_fieldset_visible(html)

    def test_hide_if_empty_fieldset_hides_static_fieldset_without_visible_fields(self):
        class EmptyFieldsetForm(SBAdminBaseFormInit, forms.Form):
            token = forms.CharField(widget=forms.HiddenInput)

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("token",),
                            "hide_if_empty": True,
                        },
                    ),
                )

        html = self.render_fieldset(EmptyFieldsetForm(request=self.request))

        self.assert_fieldset_hidden(html)

    def test_hide_if_empty_fieldset_keeps_active_dynamic_region_visible(self):
        class ActiveDynamicRegionForm(SBAdminBaseFormInit, forms.Form):
            sbadmin_dynamic_region_source = SBDynamicRegionSource.FORM

            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": (
                                SBDynamicRegion(
                                    name="details",
                                    fields=("title",),
                                ),
                            ),
                            "hide_if_empty": True,
                        },
                    ),
                )

        html = self.render_fieldset(ActiveDynamicRegionForm(request=self.request))

        self.assert_fieldset_visible(html)

    def test_hide_if_empty_fieldset_hides_empty_dynamic_region(self):
        class EmptyDynamicRegionForm(SBAdminBaseFormInit, forms.Form):
            sbadmin_dynamic_region_source = SBDynamicRegionSource.FORM

            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": (
                                SBDynamicRegion(
                                    name="details",
                                    fields=("title",),
                                    get_active_fields=lambda form, request, region: (),
                                ),
                            ),
                            "hide_if_empty": True,
                        },
                    ),
                )

        html = self.render_fieldset(EmptyDynamicRegionForm(request=self.request))

        self.assert_fieldset_hidden(html)

    def test_hide_if_empty_fieldset_keeps_fieldset_with_errors_visible(self):
        class EmptyFieldsetWithErrorsForm(SBAdminBaseFormInit, forms.Form):
            token = forms.CharField(widget=forms.HiddenInput)

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("token",),
                            "hide_if_empty": True,
                        },
                    ),
                )

        form = EmptyFieldsetWithErrorsForm(data={}, request=self.request)
        html = self.render_fieldset(form)

        self.assert_fieldset_visible(html)

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

    def test_fieldset_fields_drop_non_form_layout_items(self):
        fields = SBAdminDynamicFormMixin.get_fieldset_fields(
            {
                "fields": (
                    "title",
                    object,
                    ("subtitle", object),
                    SBDynamicRegion(name="details", fields=("summary",)),
                )
            }
        )

        self.assertEqual(fields, ("title", ("subtitle",), "summary"))

    def test_skip_header_fieldset_omits_fieldset_header(self):
        class SkipHeaderFieldsetForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("title",),
                            "skip_header": True,
                        },
                    ),
                )

        html = self.render_fieldset(SkipHeaderFieldsetForm(request=self.request))

        self.assertNotIn('data-bs-toggle="collapse"', html)
        self.assertNotIn("<header", html)
        self.assertIn('name="title"', html)

    def test_collapsible_fieldset_defaults_open(self):
        class CollapsibleFieldsetForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("title",),
                            "collapsible": True,
                        },
                    ),
                )

        html = self.render_fieldset(CollapsibleFieldsetForm(request=self.request))

        self.assertIn('data-bs-toggle="collapse"', html)
        self.assertIn('data-bs-target="#sbadmin-fieldset-details"', html)
        self.assertIn('aria-controls="sbadmin-fieldset-details"', html)
        self.assertIn('aria-expanded="true"', html)
        self.assert_collapse_body(
            html,
            "sbadmin-fieldset-details",
            "sbadmin-fieldset-collapse",
            "show",
        )

    def test_collapsible_fieldset_can_default_closed(self):
        class CollapsibleFieldsetForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Advanced",
                        {
                            "fields": ("title",),
                            "collapsible": True,
                            "default_collapsed": True,
                        },
                    ),
                )

        html = self.render_fieldset(CollapsibleFieldsetForm(request=self.request))

        self.assertIn('data-bs-target="#sbadmin-fieldset-advanced"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("collapse-btn collapsed", html)
        self.assert_collapse_body(
            html,
            "sbadmin-fieldset-advanced",
            "sbadmin-fieldset-collapse",
        )
        collapse_class = html.split('id="sbadmin-fieldset-advanced" class="', 1)[
            1
        ].split('"', 1)[0]
        self.assertNotIn(
            "show",
            collapse_class.split(),
        )

    def test_non_collapsible_fieldset_does_not_render_collapse_markup(self):
        html = self.render_fieldset(MetaFieldsetsForm(request=self.request))

        self.assertNotIn('data-bs-toggle="collapse"', html)
        self.assertNotIn("sbadmin-fieldset-collapse", html)

    def test_collapsible_unnamed_fieldset_id_uses_prefix_only(self):
        class CollapsibleUnnamedFieldsetForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()
            subtitle = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        None,
                        {
                            "fields": ("title", "subtitle"),
                            "collapsible": True,
                        },
                    ),
                )

        html = self.render_fieldset(
            CollapsibleUnnamedFieldsetForm(prefix="inline-0", request=self.request)
        )

        self.assertIn('data-bs-target="#sbadmin-fieldset-inline-0"', html)
        self.assert_collapse_body(
            html,
            "sbadmin-fieldset-inline-0",
            "sbadmin-fieldset-collapse",
            "show",
        )

    def test_collapsible_fieldset_preserves_dynamic_region_order(self):
        class CollapsibleCombinedDynamicFieldsetForm(CombinedDynamicFieldsetForm):
            view = FakeView()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        CombinedDynamicFieldsetForm.Meta.sbadmin_fieldsets[0][0],
                        {
                            **CombinedDynamicFieldsetForm.Meta.sbadmin_fieldsets[0][1],
                            "collapsible": True,
                        },
                    ),
                )

        html = self.render_fieldset(
            CollapsibleCombinedDynamicFieldsetForm(request=self.request)
        )

        self.assert_collapse_body(
            html,
            "sbadmin-fieldset-combined-details",
            "sbadmin-fieldset-collapse",
            "show",
        )
        self.assertLess(
            html.index('name="mode"'),
            html.index('id="sbadmin-dynamic-region-combined-details"'),
        )
        self.assertLess(
            html.index('id="sbadmin-dynamic-region-combined-details"'),
            html.index('name="note"'),
        )

    def test_fieldset_actions_are_permission_filtered(self):
        view = FakeFieldsetActionView(denied_action_id="hidden")
        visible_action = SBAdminCustomAction(
            title="Visible",
            view=view,
            action_id="visible",
        )
        hidden_action = SBAdminCustomAction(
            title="Hidden",
            view=view,
            action_id="hidden",
        )

        class FieldsetActionsForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("title",),
                            "actions": (visible_action, hidden_action),
                        },
                    ),
                )

        FieldsetActionsForm.view = view
        html = self.render_fieldset(FieldsetActionsForm(request=self.request))

        self.assertIn("Visible", html)
        self.assertIn("/sb-admin/visible/template", html)
        self.assertNotIn("Hidden", html)
        self.assertNotIn("/sb-admin/hidden/template", html)

    def test_fieldset_form_view_actions_are_registered_with_current_object(self):
        class FieldsetModalView(ActionModalView):
            form_class = forms.Form

        view = FakeFieldsetActionView()
        action = SBAdminFormViewAction(
            target_view=FieldsetModalView,
            title="Open modal",
            view=view,
            open_in_modal=True,
        )

        class FieldsetActionsForm(SBAdminBaseFormInit, forms.Form):
            title = forms.CharField()

            class Meta:
                sbadmin_fieldsets = (
                    (
                        "Details",
                        {
                            "fields": ("title",),
                            "actions": (action,),
                        },
                    ),
                )

        FieldsetActionsForm.view = view
        form = FieldsetActionsForm(request=self.request)
        form.instance = SimpleNamespace(pk=42)

        html = self.render_fieldset(form)

        self.assertTrue(hasattr(view, "FieldsetModalView"))
        self.assertIn("/sb-admin/FieldsetModalView/template/42", html)
        self.assertIn('data-bs-toggle="modal"', html)

    def test_action_modal_form_does_not_use_parent_view_dynamic_regions(self):
        modal = ExternalRegionActionModal(
            view=ViewWithFormSpecificRegion(),
        )
        modal.setup(self.request)
        form = modal.get_form()

        self.assertIsInstance(form.view, ViewWithFormSpecificRegion)
        self.assertEqual(form.get_dynamic_regions(self.request), ())

    def test_action_autocomplete_registration_uses_action_modal_form_wrapper(self):
        class ActionRegistrationView(
            FakeFieldsetActionView, ViewWithFormSpecificRegion
        ):
            pass

        FormWithExternalViewRegions.view = None
        view = ActionRegistrationView()
        self.request.request_data = SimpleNamespace(
            modifier=(
                f"{ExternalRegionActionModal.__name__}"
                f"{ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR}unused"
            ),
            object_id=None,
            configuration=DynamicRegionTestConfiguration(),
        )

        view.register_action_autocomplete_views(
            self.request,
            [SimpleNamespace(target_view=ExternalRegionActionModal)],
        )

        self.assertIsNone(FormWithExternalViewRegions.view)

    def test_actions_and_autocomplete_initialize_all_action_sources(self):
        parent_view = CompleteParentActionView()
        inline_view = CompleteInlineActionView()
        source_views = {
            "list_selection": parent_view,
            "list": parent_view,
            "row": parent_view,
            "detail": parent_view,
            "fieldset": parent_view,
            "inline": inline_view,
        }

        for source_name, source_view in source_views.items():
            modal_class = COMPLETE_ACTION_MODALS[source_name]
            widget_id = (
                f"{source_view.get_id()}_lookup_CompleteActionAutocompleteWidget_"
                f"{modal_class.form_class.__name__}"
            )
            action_widget_id = (
                f"{modal_class.__name__}"
                f"{ACTION_AUTOCOMPLETE_MODIFIER_SEPARATOR}{widget_id}"
            )

            action_response = self.dispatch_complete_action_request(
                source_view,
                action=modal_class.__name__,
                modifier="template",
                object_id="42",
            )
            action_payload = json.loads(action_response.content.decode())

            self.assertEqual(action_response.status_code, 200)
            self.assertEqual(action_payload["source"], source_name)
            self.assertEqual(action_payload["object_id"], "42")
            self.assertIn(action_widget_id, action_payload["autocomplete_ids"])

            autocomplete_response = self.dispatch_complete_action_request(
                source_view,
                action=Action.AUTOCOMPLETE.value,
                modifier=action_widget_id,
                object_id="42",
                method="post",
                data={"autocomplete_term": "abc"},
            )
            autocomplete_payload = json.loads(autocomplete_response.content.decode())[
                "data"
            ][0]

            self.assertEqual(autocomplete_response.status_code, 200)
            self.assertEqual(autocomplete_payload["source"], source_name)
            self.assertEqual(autocomplete_payload["field"], "lookup")
            self.assertEqual(autocomplete_payload["view"], source_view.get_id())
            self.assertEqual(autocomplete_payload["object_id"], "42")
            self.assertEqual(autocomplete_payload["modifier"], action_widget_id)

    def dispatch_complete_action_request(
        self,
        source_view,
        *,
        action,
        modifier,
        object_id=None,
        method="get",
        data=None,
    ):
        request_method = getattr(RequestFactory(), method)
        request = request_method(
            source_view.get_action_url(action, modifier, object_id),
            data=data or {},
        )
        request.user = SimpleNamespace(is_anonymous=True)
        request.session = {}
        request.request_data = CompleteActionRequestData(
            view=source_view.get_id(),
            action=action,
            modifier=modifier,
            object_id=object_id,
            user=request.user,
            request_meta=request.META,
            request_get=request.GET,
            request_post=request.POST,
            request_method=request.method,
            configuration=CompleteActionConfiguration(),
            selected_view=source_view,
            session=request.session,
            additional_data={},
            autocomplete_map={},
        )
        SBAdminThreadLocalService.set_request(request)

        with patch(
            "django_smartbase_admin.services.views."
            "SBAdminViewRequestData.from_request_and_kwargs",
            return_value=request.request_data,
        ):
            return SBAdminViewService.delegate_to_action(
                request,
                view=source_view.get_id(),
                action=action,
                modifier=modifier,
                object_id=object_id,
            )

    def test_action_modal_dynamic_regions_use_current_request_path(self):
        request = RequestFactory().get("/modal/action/")
        SBAdminThreadLocalService.set_request(request)
        modal = DynamicRegionActionModal(view=FakeView())
        modal.setup(request)
        form = modal.get_form()

        self.assertEqual(form.fields["mode"].widget.attrs["hx-post"], "/modal/action/")

    def test_action_modal_dynamic_region_initial_is_built_from_request_data(self):
        request = RequestFactory().post(
            "/modal/action/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "details",
                "mode": "digital",
            },
        )
        SBAdminThreadLocalService.set_request(request)
        modal = DynamicRegionActionModal(view=FakeView())
        modal.setup(request)

        response = modal.post(request)
        html = response.content.decode()

        self.assertIn('name="download_url"', html)
        self.assertIn('name="billing_period"', html)
        self.assertNotIn('name="weight"', html)

    def test_standalone_form_view_dynamic_region_initial_is_built_from_request_data(
        self,
    ):
        request = RequestFactory().post(
            "/standalone/action/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "details",
                "mode": "digital",
            },
        )
        SBAdminThreadLocalService.set_request(request)
        view = DynamicRegionStandaloneView(view=FakeView())
        view.setup(request)

        response = view.post(request)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="download_url"', html)
        self.assertIn('name="billing_period"', html)
        self.assertNotIn('name="weight"', html)
        self.assertNotIn("This field is required", html)

    def test_action_modal_dynamic_region_response_includes_related_regions(self):
        request = RequestFactory().post(
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

        response = modal.post(request)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="sbadmin-dynamic-region-primary-region"', html)
        self.assertIn('id="sbadmin-dynamic-region-secondary-region"', html)
        self.assertIn('name="primary"', html)
        self.assertIn('name="secondary"', html)
        self.assertEqual(html.count('hx-swap-oob="outerHTML"'), 2)

    def test_row_action_modal_dynamic_region_initial_uses_object(self):
        request = RequestFactory().post(
            "/modal/row/123/",
            {
                SBADMIN_DYNAMIC_REGION_PARAM: "row_details",
            },
        )
        SBAdminThreadLocalService.set_request(request)
        modal = RowObjectDynamicRegionModal(view=FakeView())
        modal.setup(request, modifier="123")

        response = modal.post(request)
        html = response.content.decode()

        self.assertIn('name="email"', html)
        self.assertNotIn('name="last_name"', html)

    def test_model_admin_get_fieldsets_preserves_fields_container_type(self):
        model_admin = dynamic_region_admin_site._registry[DynamicRegionDemoModel]

        fieldsets = model_admin.get_fieldsets(self.request)
        fields = fieldsets[0][1]["fields"]

        self.assertIsInstance(fields, tuple)
        self.assertEqual(fields, ("username", "first_name", "last_name"))

        class ListFieldsetsAdmin(SBAdmin):
            sbadmin_fieldsets = (
                (
                    "Profile",
                    {
                        "fields": [
                            "username",
                            SBDynamicRegion(
                                name="profile",
                                fields=("first_name", "last_name"),
                            ),
                        ],
                    },
                ),
            )

        list_model_admin = ListFieldsetsAdmin(DynamicRegionDemoModel, AdminSite())
        list_fieldsets = list_model_admin.get_fieldsets(self.request)
        list_fields = list_fieldsets[0][1]["fields"]

        self.assertIsInstance(list_fields, list)
        self.assertEqual(list_fields, ["username", "first_name", "last_name"])

        list_fields.remove("first_name")

        configured_fields = ListFieldsetsAdmin.sbadmin_fieldsets[0][1]["fields"]
        self.assertIsInstance(configured_fields, list)
        self.assertEqual(configured_fields[1].fields, ("first_name", "last_name"))

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
        self.assertIn("js-stacked-inline-collapse", html)
        self.assertIn('data-sbadmin-dynamic-region="inline_details"', html)
        self.assertIn('hx-target="#sbadmin-dynamic-region-', html)
        self.assertIn('-0-summary"', html)
        self.assertNotIn('-0-notes"', html)

    @override_settings(ROOT_URLCONF=__name__)
    def test_stacked_inline_dynamic_region_fragment_uses_form_prefix(self):
        model_admin = dynamic_region_admin_site._registry[DynamicRegionInlineParent]
        request = RequestFactory().post(
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
            sbadmin_dynamic_region_source = SBDynamicRegionSource.FORM

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

        self.assertEqual(attrs["hx-post"], "/sb-admin/sbadmin_dynamic_region/add")
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

    def test_dynamic_region_can_render_admin_readonly_fields(self):
        form = ReadonlyDynamicRegionForm(
            instance=DynamicRegionDemoModel(username="demo"),
            request=self.request,
        )
        region = form.get_dynamic_region("readonly_details", self.request)
        state = form.get_dynamic_region_state(region, self.request)

        html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {"dynamic_region": form.get_dynamic_region_context(region, self.request)},
            request=self.request,
        )

        self.assertEqual(state.active_fields, ("readonly_summary",))
        self.assertIn("Summary", html)
        self.assertIn("Summary for demo", html)
        self.assertNotIn('name="readonly_summary"', html)

    def test_dynamic_region_readonly_fields_treat_unsaved_instance_as_add(self):
        class AddAwareReadonlyRegionView(ReadonlyDynamicRegionView):
            def get_readonly_fields(self, request, obj=None):
                return ("readonly_summary",) if obj else ()

        tracking_view = AddAwareReadonlyRegionView()

        class AddAwareReadonlyRegionForm(ReadonlyDynamicRegionForm):
            view = tracking_view

        add_form = AddAwareReadonlyRegionForm(
            instance=DynamicRegionDemoModel(username="demo"),
            request=self.request,
        )
        add_region = add_form.get_dynamic_region("readonly_details", self.request)
        add_state = add_form.get_dynamic_region_state(add_region, self.request)

        change_form = AddAwareReadonlyRegionForm(
            instance=DynamicRegionDemoModel(id=1, username="demo"),
            request=self.request,
        )
        change_region = change_form.get_dynamic_region("readonly_details", self.request)
        change_state = change_form.get_dynamic_region_state(change_region, self.request)

        self.assertEqual(add_form.get_dynamic_region_readonly_fields(self.request), ())
        self.assertEqual(add_state.active_fields, ())
        self.assertEqual(
            change_form.get_dynamic_region_readonly_fields(self.request),
            ("readonly_summary",),
        )
        self.assertEqual(change_state.active_fields, ("readonly_summary",))
        self.assertEqual(
            add_form._dynamic_region_endpoint(self.request),
            "/sb-admin/sbadmin_dynamic_region/add",
        )
        self.assertEqual(
            change_form._dynamic_region_endpoint(self.request),
            "/sb-admin/sbadmin_dynamic_region/add/1",
        )

    def test_deferred_dynamic_region_renders_lazy_loader_until_fragment(self):
        form = DeferredDynamicRegionForm(request=self.request)
        region = form.get_dynamic_region("lazy_details", self.request)

        initial_html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {"dynamic_region": form.get_dynamic_region_context(region, self.request)},
            request=self.request,
        )
        fragment_html = render_to_string(
            "sb_admin/includes/dynamic_region.html",
            {
                "dynamic_region": form.get_dynamic_region_context(
                    region, self.request, is_fragment=True
                ),
            },
            request=self.request,
        )

        self.assertIn('hx-post="/sb-admin/sbadmin_dynamic_region/add"', initial_html)
        self.assertIn('hx-trigger="load"', initial_html)
        self.assertIn('hx-target="#sbadmin-dynamic-region-lazy-details"', initial_html)
        self.assertIn('hx-swap="none"', initial_html)
        self.assertIn(
            "&quot;sbadmin_dynamic_region&quot;: &quot;lazy_details&quot;", initial_html
        )
        self.assertNotIn('name="details"', initial_html)
        self.assertIn('hx-swap-oob="outerHTML"', fragment_html)
        self.assertIn('name="details"', fragment_html)
        self.assertNotIn('hx-trigger="load"', fragment_html)

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
                "dynamic_region": form.get_dynamic_region_context(
                    region, self.request, is_fragment=True
                ),
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

    def test_dynamic_region_initial_includes_uploaded_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        class UploadForm(forms.Form):
            attachment = forms.FileField()

        uploaded = SimpleUploadedFile(
            "preview.jpg", b"preview-bytes", content_type="image/jpeg"
        )
        data = QueryDict("attachment=")
        files = {"attachment": uploaded}

        initial = SBAdmin._dynamic_region_initial_from_data(
            UploadForm,
            data,
            {},
            files,
        )

        self.assertIs(initial["attachment"], uploaded)

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
                "dynamic_region": form.get_dynamic_region_context(
                    region, self.request, is_fragment=True
                ),
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
                "dynamic_region": form.get_dynamic_region_context(
                    region, self.request, is_fragment=True
                ),
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


class SBDynamicRegionWrapperIdTests(SimpleTestCase):
    def test_get_wrapper_id_preserves_formset_prefix_placeholder(self):
        region = SBDynamicRegion(
            name="carrier_type_region",
            trigger_fields=("shipper",),
            fields=("carrier_type",),
        )
        form = forms.Form(prefix="settings_shipper_mappings-__prefix__")
        wrapper_id = region.get_wrapper_id(form)
        self.assertEqual(
            wrapper_id,
            "sbadmin-dynamic-region-settings-shipper-mappings-__prefix__-carrier-type-region",
        )
        self.assertNotIn("---prefix---", wrapper_id)

    def test_get_wrapper_id_slugifies_normal_prefix(self):
        region = SBDynamicRegion(
            name="carrier_type_region",
            trigger_fields=("shipper",),
            fields=("carrier_type",),
        )
        form = forms.Form(prefix="settings_shipper_mappings-0")
        wrapper_id = region.get_wrapper_id(form)
        self.assertEqual(
            wrapper_id,
            "sbadmin-dynamic-region-settings-shipper-mappings-0-carrier-type-region",
        )
