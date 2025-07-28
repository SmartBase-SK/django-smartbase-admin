from django import forms
from django.http import HttpResponse
from django.views.generic import FormView

from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit
from django_smartbase_admin.admin.widgets import (
    SBAdminRadioDropdownWidget,
)
from django_smartbase_admin.models import SBAdminUserConfiguration


class ColorSchemeForm(SBAdminBaseFormInit, forms.ModelForm):
    class Meta:
        model = SBAdminUserConfiguration
        fields = ("color_scheme",)
        widgets = {
            "color_scheme": SBAdminRadioDropdownWidget(),
        }
        required = []


class ColorSchemeView(FormView):
    form_class = ColorSchemeForm

    def form_valid(self, form):
        instance = form.save(commit=False)
        sb_admin_user_config = SBAdminUserConfiguration.objects.get(
            user_id=self.request.user.id
        )
        sb_admin_user_config.color_scheme = instance.color_scheme
        sb_admin_user_config.save(update_fields=["color_scheme"])
        return HttpResponse(status=200)
