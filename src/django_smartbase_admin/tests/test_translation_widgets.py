from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock

from ckeditor_uploader.fields import RichTextUploadingField
from django import forms
from django.contrib.admin import AdminSite
from django.db import models
from django.forms import modelform_factory
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from filer.fields.image import FilerImageField
from filer.models import Image

from django_smartbase_admin.admin.widgets import (
    SBAdminCKEditorUploadingWidget,
    SBAdminFilerImagePickerWidget,
    SBAdminMultipleChoiceInlineWidget,
    SBAdminSelectWidget,
    SBAdminTextareaWidget,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.views.translations_view import ModelTranslationView


class TranslatedArticle(models.Model):
    content = RichTextUploadingField(config_name="blog_config")
    excerpt = models.TextField(blank=True)

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


def get_image_model_field():
    model_field = FilerImageField(null=True, on_delete=models.SET_NULL)
    model_field.remote_field.model = Image
    model_field.remote_field.field_name = Image._meta.pk.name
    model_field.set_attributes_from_name("image")
    return model_field


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


class _ChoicesProtocolWidget(forms.TextInput):
    choices = ()

    def __init__(self, form_field=None, attrs=None):
        self.form_field = form_field
        super().__init__(attrs)


class TranslationWidgetTests(SimpleTestCase):
    def test_translation_view_excludes_configured_model_fields(self):
        included_field = mock.Mock(name="included_field")
        included_field.name = "title"
        excluded_field = mock.Mock(name="excluded_field")
        excluded_field.name = "route_site"
        translation_model = mock.Mock()
        translation_model._meta.get_fields.return_value = (
            included_field,
            excluded_field,
        )
        model = mock.Mock()
        model._parler_meta.get_all_models.return_value = (translation_model,)

        translated_fields = ModelTranslationView(
            model=model,
            exclude_fields=("route_site",),
        ).get_translated_fields()

        self.assertEqual(translated_fields, {translation_model: [included_field]})

    def test_default_choice_widgets_keep_field_choices(self):
        choices = (("draft", "Draft"), ("published", "Published"))
        cases = (
            (forms.ChoiceField(choices=choices), SBAdminSelectWidget),
            (forms.TypedChoiceField(choices=choices), SBAdminSelectWidget),
            (
                forms.MultipleChoiceField(choices=choices),
                SBAdminMultipleChoiceInlineWidget,
            ),
            (
                forms.TypedMultipleChoiceField(choices=choices),
                SBAdminMultipleChoiceInlineWidget,
            ),
        )

        for form_field, expected_widget_class in cases:
            with self.subTest(form_field=form_field.__class__.__name__):
                ModelTranslationView().assign_widget_to_form_field(form_field)

                self.assertIsInstance(form_field.widget, expected_widget_class)
                self.assertEqual(list(form_field.widget.choices), list(choices))

    def test_choices_are_assigned_by_widget_protocol(self):
        form_field = forms.ChoiceField(choices=(("draft", "Draft"),))
        view = ModelTranslationView()
        view.django_widget_to_widget = {
            forms.Select: _ChoicesProtocolWidget,
        }

        view.assign_widget_to_form_field(form_field)

        self.assertIsInstance(form_field.widget, _ChoicesProtocolWidget)
        self.assertEqual(form_field.widget.choices, form_field.choices)

    def test_translation_count_uses_non_null_check_for_relation_fields(self):
        field = get_image_model_field()

        condition = SBAdminTranslationsService.get_translation_field_value_condition(
            "translation_en",
            field,
        )

        self.assertEqual(
            condition.children,
            [("translation_en__image__isnull", False)],
        )

    def test_translation_count_uses_non_empty_check_for_text_fields(self):
        field = TranslatedArticle._meta.get_field("content")

        condition = SBAdminTranslationsService.get_translation_field_value_condition(
            "translation_en",
            field,
        )

        self.assertEqual(
            condition.children[0],
            ("translation_en__content__isnull", False),
        )
        self.assertTrue(condition.children[1].negated)
        self.assertEqual(
            condition.children[1].children,
            [("translation_en__content", "")],
        )

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

    def test_text_field_keeps_textarea_widget(self):
        form_class = modelform_factory(TranslatedArticle, fields=("excerpt",))
        form_field = form_class.base_fields["excerpt"]
        db_field = TranslatedArticle._meta.get_field("excerpt")

        ModelTranslationView().assign_widget_to_form_field(
            form_field,
            db_field=db_field,
        )

        self.assertIsInstance(form_field.widget, SBAdminTextareaWidget)

    def test_filer_image_widget_supports_translation_view(self):
        db_field = get_image_model_field()
        form_field = db_field.formfield()
        form_field.widget.attrs["form"] = "translation-form-sk"
        form_field.widget.attrs["readonly"] = True
        admin_site = AdminSite(name="translation-test")
        view = ModelTranslationView()
        view.init_view_static(
            SimpleNamespace(view_map={}),
            TranslatedArticle,
            admin_site,
        )

        view.assign_widget_to_form_field(
            form_field,
            db_field=db_field,
        )

        self.assertIsInstance(form_field.widget, SBAdminFilerImagePickerWidget)
        self.assertIs(form_field.widget.admin_site, admin_site)
        with (
            mock.patch(
                "django_smartbase_admin.admin.widgets.reverse",
                return_value="/media-picker/",
            ),
            mock.patch.object(
                form_field.widget,
                "get_selected_object",
                return_value=None,
            ),
            mock.patch(
                "django_smartbase_admin.admin.widgets.FilerMediaPickerService.upload_url",
                return_value="/upload/",
            ),
        ):
            html = form_field.widget.render(
                "meta_image",
                None,
                attrs={"id": "id_meta_image"},
            )

        self.assertIn('form="translation-form-sk"', html)
        self.assertIn('data-picker-readonly="true"', html)
        self.assertIn("readonly", html)
        self.assertNotIn("data-sb-media-picker-trigger", html)
        self.assertNotIn("data-picker-clear", html)
        self.assertNotIn(">Delete<", html)
        self.assertNotIn('class="js-filer-dropzone filer-dropzone', html)
        self.assertEqual(html.count('id="id_meta_image"'), 1)
        self.assertIn('id="id_meta_image-selected-item"', html)

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
