from ckeditor_uploader.fields import RichTextUploadingField
from django.db import models
from django.forms import modelform_factory
from django.test import SimpleTestCase

from django_smartbase_admin.admin.widgets import SBAdminCKEditorUploadingWidget
from django_smartbase_admin.views.translations_view import ModelTranslationView


class TranslatedArticle(models.Model):
    content = RichTextUploadingField(config_name="blog_config")

    class Meta:
        app_label = "django_smartbase_admin"
        managed = False


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
