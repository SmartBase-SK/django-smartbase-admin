from html.parser import HTMLParser

from ckeditor_uploader.fields import RichTextUploadingField
from django import forms
from django.db import models
from django.forms import modelform_factory
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from django_smartbase_admin.admin.widgets import SBAdminCKEditorUploadingWidget
from django_smartbase_admin.views.translations_view import ModelTranslationView


class TranslatedArticle(models.Model):
    content = RichTextUploadingField(config_name="blog_config")

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


class _TranslationDetailStructureParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ancestors = []
        self.error_alert_inside_field_grid = False

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if (
            "alert" in classes
            and "bg-negative-50" in classes
            and any(
                {"flex", "flex-wrap", "-mx-32"}.issubset(ancestor)
                for ancestor in self.ancestors
            )
        ):
            self.error_alert_inside_field_grid = True
        if tag not in {"input", "link", "meta", "hr", "img", "br"}:
            self.ancestors.append(set(classes))

    def handle_endtag(self, tag):
        if tag not in {"input", "link", "meta", "hr", "img", "br"}:
            self.ancestors.pop()


class _InvalidTranslationForm(forms.Form):
    name = forms.CharField()
    model_table = "translated_article"

    def clean(self):
        raise forms.ValidationError("Translation constraint failed.")


class TranslationWidgetTests(SimpleTestCase):
    def test_uploading_ckeditor_keeps_model_field_config(self):
        form_class = modelform_factory(TranslatedArticle, fields=("content",))
        form_field = form_class.base_fields["content"]
        db_field = TranslatedArticle._meta.get_field("content")

        ModelTranslationView().assign_widget_to_form_field(
            form_field,
            db_field=db_field,
        )

        self.assertIsInstance(form_field.widget, SBAdminCKEditorUploadingWidget)
        self.assertEqual(form_field.widget.config_name, "blog_config")

    def test_non_field_errors_render_outside_translation_field_grid(self):
        form = _InvalidTranslationForm({"en-name": "Duplicate"}, prefix="en")
        self.assertFalse(form.is_valid())
        request = RequestFactory().get(
            "/translations/", HTTP_SEC_FETCH_SITE="same-origin"
        )
        request.LANGUAGE_CODE = "en"

        html = render_to_string(
            "sb_admin/actions/translations-detail.html",
            {
                "request": request,
                "translation_forms": {"en": [form]},
                "languages_form": forms.Form(),
                "FORM_BASE_ID": "translation-form-",
                "TRANSLATION_MODEL_KEY": "model_table",
                "main_language_code": "en",
                "back_url": "/articles/",
                "title": "Translations",
            },
            request=request,
        )

        parser = _TranslationDetailStructureParser()
        parser.feed(html)

        self.assertIn("alert bg-negative-50", html)
        self.assertIn("Please correct the error below.", html)
        self.assertIn("Translation constraint failed.", html)
        self.assertFalse(parser.error_alert_inside_field_grid)
