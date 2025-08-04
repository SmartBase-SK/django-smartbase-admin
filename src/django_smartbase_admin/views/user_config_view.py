from django import forms
from django.http import HttpResponse
from django.utils.html import format_html
from django.views.generic import FormView

from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit
from django_smartbase_admin.admin.widgets import (
    SBAdminRadioDropdownWidget,
)
from django_smartbase_admin.models import SBAdminUserConfiguration, ColorScheme
from django_smartbase_admin.services.configuration import (
    SBAdminUserConfigurationService,
)


class ColorSchemeForm(SBAdminBaseFormInit, forms.ModelForm):
    color_scheme_icons = {
        ColorScheme.AUTO.value: "Translation",
        ColorScheme.DARK.value: "Moon",
        ColorScheme.LIGHT.value: "Sun-one",
    }

    class Meta:
        model = SBAdminUserConfiguration
        fields = ("color_scheme",)
        widgets = {
            "color_scheme": SBAdminRadioDropdownWidget(),
        }
        required = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices_formatted = []
        for choice in self.fields["color_scheme"].choices:
            choice_label = format_html(
                f'<span class="flex gap-8"><svg class="w-20 h-20"><use href="#{self.color_scheme_icons.get(choice[0])}"></use></svg><span>{choice[1]}</span></span>'
            )
            choices_formatted.append((choice[0], choice_label))
        self.fields["color_scheme"].choices = choices_formatted


class ColorSchemeView(FormView):
    form_class = ColorSchemeForm

    def form_valid(self, form):
        instance = form.save(commit=False)
        sb_admin_user_config = SBAdminUserConfigurationService.get_user_config(
            self.request
        )
        sb_admin_user_config.color_scheme = instance.color_scheme
        sb_admin_user_config.save(update_fields=["color_scheme"])
        return HttpResponse(status=200)
