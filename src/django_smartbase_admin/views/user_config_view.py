from django import forms
from django.conf import settings
from django.http import HttpResponse
from django.templatetags.static import static
from django.utils import translation
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
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
            "color_scheme": SBAdminRadioDropdownWidget(
                attrs={"button_class": "shadow-none"}
            ),
        }
        required = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices_formatted = []
        for choice in self.fields["color_scheme"].choices:
            choice_label = format_html(
                '<span class="flex gap-8"><svg class="w-20 h-20"><use href="#{}"></use></svg><span>{}</span></span>',
                self.color_scheme_icons.get(choice[0]),
                choice[1],
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


class LanguageForm(SBAdminBaseFormInit, forms.Form):
    language = forms.ChoiceField(
        label=_("Language"),
        choices=(),
        widget=SBAdminRadioDropdownWidget(attrs={"button_class": "shadow-none"}),
    )
    next = forms.CharField(widget=forms.HiddenInput(), required=False)

    @staticmethod
    def get_flag_static_path(lang_code: str) -> str:
        base = lang_code.split("-", 1)[0]
        return static(f"sb_admin/images/flags/{base}.png")

    @classmethod
    def resolve_active_language_code(cls, languages: list[tuple[str, str]]) -> str:
        codes = [code for code, _ in languages]
        if not codes:
            return translation.get_language()

        current = translation.get_language()
        if current in codes:
            return current

        current_base = current.split("-", 1)[0]
        for code in codes:
            if code == current_base or code.startswith(f"{current_base}-"):
                return code

        default_language = settings.LANGUAGE_CODE
        if default_language in codes:
            return default_language

        return codes[0]

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, request=request, **kwargs)
        choices_formatted = []
        for lang_code, lang_name in settings.LANGUAGES:
            flag_src = self.get_flag_static_path(lang_code)
            choice_label = format_html(
                '<span class="inline-flex items-center gap-8">'
                '<img src="{}" alt="{}" class="w-24 h-18 border border-dark-200 rounded-xs" width="24" height="18" loading="lazy">'
                "<span>{}</span></span>",
                flag_src,
                lang_name,
                lang_name,
            )
            choices_formatted.append((lang_code, choice_label))
        self.fields["language"].choices = choices_formatted

        if request is not None and not self.is_bound:
            self.fields["next"].initial = request.get_full_path()
            self.fields["language"].initial = self.resolve_active_language_code(
                list(settings.LANGUAGES)
            )
