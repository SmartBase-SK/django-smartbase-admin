import copy

from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.db.models import BooleanField, Case, Q, Value, When
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.defaultfilters import filesizeformat
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from filer.admin import FileAdmin, FolderAdmin
from filer.admin.fileadmin import FileAdminChangeFrom
from filer.models import File, Folder, Image

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminThirdParty
from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import boolean_formatter
from django_smartbase_admin.engine.filter_widgets import BooleanFilterWidget
from django_smartbase_admin.utils import (
    SBAdminNoHistoryDetailMixin,
    sb_admin_filer_directory_listing_url_for_file,
)


def redirect_to_sb_admin(response):
    if isinstance(response, HttpResponseRedirect):
        response["Location"] = response["Location"].replace(
            reverse("admin:index"), reverse("sb_admin:index")
        )
    return response


def filer_canonical_url_enabled():
    try:
        reverse("canonical", kwargs={"uploaded_at": 0, "file_id": 0})
    except NoReverseMatch:
        return False
    return True


class SBAdminFilerFolderAdmin(SBAdminThirdParty, FolderAdmin):
    directory_listing_template = "sb_admin/integrations/filer/folder_list.html"
    change_form_template = "sb_admin/actions/change_form.html"
    autocomplete_fields = []

    def get_autocomplete_fields(self, request):
        # filer's version looks up the User admin on this site, which may not exist.
        return []

    def directory_listing(self, request, folder_id=None, viewtype=None):
        return redirect_to_sb_admin(
            super().directory_listing(request, folder_id, viewtype)
        )


class SBAdminFilerFileForm(FileAdminChangeFrom):
    class Meta(FileAdminChangeFrom.Meta):
        labels = {
            "name": _("Name"),
            "mime_type": _("File type"),
            "uploaded_at": _("Created"),
            "modified_at": _("Modified"),
            "sha1": _("SHA-1"),
            "display_canonical": _("Canonical URL"),
            "file": "",
        }
        help_texts = {
            "name": _("Shown in the media library instead of the file name."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "file" in self.fields:
            # FileAdminChangeFrom swaps the SB admin widget for a plain FileInput.
            self.fields["file"].widget = copy.deepcopy(self.base_fields["file"].widget)
            self.fields["file"].required = True
            self.fields["file"].widget.is_required = True


class SBAdminFilerImageForm(SBAdminFilerFileForm):
    class Meta(SBAdminFilerFileForm.Meta):
        labels = {
            **SBAdminFilerFileForm.Meta.labels,
            "default_alt_text": _("Alt text"),
        }
        help_texts = {
            **SBAdminFilerFileForm.Meta.help_texts,
            "default_alt_text": _(
                "Describes the image for screen readers and search engines. "
                "Used wherever the image has no alt text of its own."
            ),
        }


class SBAdminFilerFileAdmin(SBAdminNoHistoryDetailMixin, SBAdmin, FileAdmin):
    form = SBAdminFilerFileForm
    autocomplete_fields = []
    sbadmin_list_display = (
        SBAdminField(name="original_filename", title=_("File name")),
        SBAdminField(name="name", title=_("Name")),
        SBAdminField(name="mime_type", title=_("File type")),
        SBAdminField(name="uploaded_at", title=_("Created")),
    )
    ordering = ("-uploaded_at",)
    readonly_fields = [
        *FileAdmin.readonly_fields,
        "mime_type",
        "file_size",
        "uploaded_at",
        "modified_at",
    ]
    fieldsets = [
        (None, {"fields": ["name", "owner", "description"]}),
        (
            _("Details"),
            {
                "fields": [
                    ("mime_type", "file_size"),
                    "uploaded_at",
                    "modified_at",
                    "sha1",
                    "display_canonical",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            _("Change file"),
            {
                "fields": ["file"],
                "description": _(
                    "The new file replaces this one everywhere it is used."
                ),
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
    ]

    def get_sbadmin_fieldsets(self, request, object_id=None):
        fieldsets = super().get_sbadmin_fieldsets(request, object_id)
        if filer_canonical_url_enabled():
            return fieldsets
        return [
            (
                name,
                {
                    **options,
                    "fields": [
                        field
                        for field in options["fields"]
                        if field != "display_canonical"
                    ],
                },
            )
            for name, options in fieldsets
        ]

    def get_autocomplete_fields(self, request):
        # filer's version looks up the User admin on this site, which may not exist.
        return []

    @admin.display(description=_("Size"))
    def file_size(self, obj):
        return filesizeformat(obj.size)

    def get_change_view_context(self, request, object_id):
        """Back → folder listing for ``logical_folder`` (same path as filer breadcrumbs; no breadcrumb UI)."""
        ctx = super().get_change_view_context(request, object_id)
        ctx["show_save_and_add_another"] = False
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            return ctx
        ctx["back_url"] = sb_admin_filer_directory_listing_url_for_file(obj)
        ctx["back_url_add_preserved_filters"] = False
        return ctx

    def get_sbadmin_detail_actions(self, request, object_id=None):
        actions = list(super().get_sbadmin_detail_actions(request, object_id) or [])
        obj = self.get_object(request, unquote(object_id)) if object_id else None
        if obj is not None and obj.file:
            actions.append(
                SBAdminCustomAction(
                    title=_("Download"), url=obj.url, open_in_new_tab=True
                )
            )
        return actions

    def response_change(self, request, obj):
        return redirect_to_sb_admin(super().response_change(request, obj))

    def delete_view(self, request, object_id, extra_context=None):
        return redirect_to_sb_admin(
            super().delete_view(request, object_id, extra_context)
        )

    def add_view(self, request, form_url="", extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied
        return HttpResponseRedirect(reverse("sb_admin:filer-directory_listing-root"))


class SBAdminFilerImageAdmin(SBAdminFilerFileAdmin):
    mcp_description = (
        "Images in the media library (django-filer). default_alt_text is the "
        "image's alt text, used wherever the image has no alt text of its own; "
        "set it with update_detail. Find images without one with list_rows "
        "and filter_data {'has_alt_text': False}."
    )
    form = SBAdminFilerImageForm
    sbadmin_list_display = (
        SBAdminField(name="original_filename", title=_("File name")),
        SBAdminField(name="name", title=_("Name")),
        SBAdminField(name="default_alt_text", title=_("Alt text")),
        SBAdminField(
            name="has_alt_text",
            title=_("Has alt text"),
            annotate=Case(
                When(
                    Q(default_alt_text__isnull=True) | Q(default_alt_text=""),
                    then=Value(False),
                ),
                default=Value(True),
                output_field=BooleanField(),
            ),
            filter_widget=BooleanFilterWidget(),
            python_formatter=boolean_formatter,
        ),
        SBAdminField(name="uploaded_at", title=_("Created")),
    )
    sbadmin_list_filter = ("has_alt_text",)
    search_fields = [*FileAdmin.search_fields, "default_alt_text"]
    readonly_fields = [*SBAdminFilerFileAdmin.readonly_fields, "preview", "dimensions"]
    fieldsets = [
        (None, {"fields": ["preview"]}),
        (
            _("Metadata"),
            {
                "fields": ["name", "default_alt_text"],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            _("Change image"),
            {
                "fields": ["file"],
                "description": _(
                    "The new image replaces this one everywhere it is used."
                ),
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            _("Details"),
            {
                "fields": [
                    ("mime_type", "dimensions", "file_size"),
                    "uploaded_at",
                    "modified_at",
                    "sha1",
                    "display_canonical",
                ],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
    ]

    @admin.display(description=_("Image"))
    def preview(self, obj):
        if not obj.file:
            return "-"
        return format_html(
            '<img src="{}" alt="{}" style="max-width:100%;max-height:560px;height:auto">',
            obj.url,
            obj.default_alt_text or "",
        )

    @admin.display(description=_("Dimensions"))
    def dimensions(self, obj):
        return f"{obj.width:g}×{obj.height:g} px"


def register_filer_admins(site):
    for model, model_admin in (
        (Folder, SBAdminFilerFolderAdmin),
        (File, SBAdminFilerFileAdmin),
        (Image, SBAdminFilerImageAdmin),
    ):
        if not site.is_registered(model):
            site.register(model, model_admin)
