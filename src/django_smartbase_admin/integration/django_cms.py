from django_smartbase_admin.admin.site import sb_admin_site

from django_smartbase_admin.admin.admin_base import SBAdmin


class DjangoCMSPluginSBAdmin(SBAdmin):
    initialised = False
    list_display = []

    def get_inline_instances(self, request, obj=None):
        inline_instances = super().get_inline_instances(request, obj)
        if not self.initialised:
            for inline_instance in inline_instances:
                inline_instance.init_view_static(
                    request.request_data.configuration,
                    inline_instance.model,
                    sb_admin_site,
                )
            self.initialised = True
        return inline_instances

    def get_sbadmin_fieldsets(self, request, object_id=None):
        obj = self.model.objects.get(pk=object_id) if object_id else None
        fieldsets = self.sbadmin_fieldsets or [
            (
                None,
                {"fields": self.get_fields(request, obj)},
            )
        ]
        self.sbadmin_fieldsets = fieldsets
        return fieldsets

    def response_add(self, request, obj, **kwargs):
        # response_add from CMSPluginBase
        self.object_successfully_changed = True
        return self.render_close_frame(request, obj)
