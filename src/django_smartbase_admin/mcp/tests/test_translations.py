from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldError
from django.db import connection, models
from django.test import TransactionTestCase, override_settings
from django.urls import path

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.const import TRANSLATION_MODEL_KEY
from django_smartbase_admin.mcp.bridge import bind_sbadmin_request_data
from django_smartbase_admin.mcp.mcp import SBAdminTools
from django_smartbase_admin.mcp.service import SBAdminMCPDetailService
from django_smartbase_admin.mcp.tests._common import (
    MCPToolTestConfig,
    build_mcp_request,
)
from django_smartbase_admin.mcp.translations import SBAdminMCPTranslationService
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.views.translations_view import SBAdminTranslationsView


class MCPTranslatedArticle(models.Model):
    class Meta:
        app_label = "django_smartbase_admin"

    def __str__(self):
        return str(self.pk)


class MCPTranslationTag(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "django_smartbase_admin"

    def __str__(self):
        return self.name


class MCPTranslatedArticleTranslation(models.Model):
    master = models.ForeignKey(
        MCPTranslatedArticle,
        related_name="translations",
        on_delete=models.CASCADE,
    )
    language_code = models.CharField(max_length=15)
    title = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    tags = models.ManyToManyField(MCPTranslationTag, blank=True)

    class Meta:
        app_label = "django_smartbase_admin"
        unique_together = (("language_code", "master"),)


class _MCPTranslatedArticleParlerMeta:
    def get_all_models(self):
        return (MCPTranslatedArticleTranslation,)

    def __getitem__(self, translation_model):
        return SimpleNamespace(rel_name="translations")

    def get_model_by_field(self, field_name):
        if field_name in {"title", "slug", "tags"}:
            return MCPTranslatedArticleTranslation
        raise FieldError(field_name)


MCPTranslatedArticle._parler_meta = _MCPTranslatedArticleParlerMeta()


urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(
    ROOT_URLCONF=__name__,
    SB_ADMIN_CONFIGURATION="tests.sbadmin_config.MCPSBAdminConfiguration",
    LANGUAGE_CODE="en",
    LANGUAGES=(("en", "English"), ("de", "German"), ("fr", "French")),
)
class TranslationMCPTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(MCPTranslatedArticle)
            schema_editor.create_model(MCPTranslationTag)
            schema_editor.create_model(MCPTranslatedArticleTranslation)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(MCPTranslatedArticleTranslation)
            schema_editor.delete_model(MCPTranslationTag)
            schema_editor.delete_model(MCPTranslatedArticle)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.configuration = MCPToolTestConfig()
        self._registered_views = self.configuration.registered_views
        self._view_map = self.configuration.view_map
        translations = SBAdminTranslationsView(
            translations_definition=[
                {
                    "model_path": ("django_smartbase_admin.MCPTranslatedArticle"),
                    "fields": ["title", "slug", "tags"],
                }
            ]
        )
        self.configuration.registered_views = [translations]
        self.configuration.view_map = {}
        self.configuration.init_registered_views()
        self.configuration.init_view_map()
        MCPToolTestConfig.view_permission_for = None

        self.article = MCPTranslatedArticle.objects.create()
        self.first_tag = MCPTranslationTag.objects.create(name="First")
        self.second_tag = MCPTranslationTag.objects.create(name="Second")
        MCPTranslatedArticleTranslation.objects.create(
            master=self.article,
            language_code="en",
            title="Source title",
            slug="source-title",
        )
        self.german_translation = MCPTranslatedArticleTranslation.objects.create(
            master=self.article,
            language_code="de",
            title="German title",
            slug="german-title",
        )
        self.german_translation.tags.add(self.first_tag)

        self.view_id = SBAdminTranslationsService.get_translation_view_id(
            MCPTranslatedArticle
        )
        self.translation_table = MCPTranslatedArticleTranslation._meta.db_table
        user = get_user_model().objects.create_superuser(
            username="translation-admin",
            email="translation@example.com",
            password="password",
        )
        self.tools = SBAdminTools(request=build_mcp_request(user))

    def tearDown(self):
        MCPToolTestConfig.view_permission_for = None
        self.configuration.registered_views = self._registered_views
        self.configuration.view_map = self._view_map
        super().tearDown()

    def test_translation_view_is_discoverable_and_listable(self):
        english_translation = MCPTranslatedArticleTranslation.objects.get(
            master=self.article,
            language_code="en",
        )
        english_translation.tags.set([self.first_tag, self.second_tag])
        view = self.tools.request.request_data.configuration.view_map[self.view_id]
        self.assertIs(
            SBAdminMCPDetailService.for_view(view),
            SBAdminMCPTranslationService,
        )

        index = self.tools.list_admins(detail="index")["admin_views"]
        self.assertIn(self.view_id, {entry["view_id"] for entry in index})

        entry = self.tools.list_admins(view_id=self.view_id)["admin_views"][0]
        self.assertEqual(entry["detail_fields"], ["title", "slug", "tags"])
        field_names = {field["name"] for field in entry["fields"]}
        source_title_key = f"{self.translation_table}_en__title"
        self.assertIn("title", field_names)
        self.assertIn("tags", field_names)
        self.assertIn(f"{self.translation_table}_de_status", field_names)
        self.assertIn(f"{self.translation_table}_fr_status", field_names)

        result = self.tools.list_rows(
            view_id=self.view_id,
            fields=["title", "tags"],
            filter_data={
                "tags": [{"value": self.first_tag.pk, "label": "First"}],
            },
        )
        self.assertEqual(result["last_row"], 1)
        self.assertIn("title", result["data"][0], result)
        self.assertNotIn(source_title_key, result["data"][0], result)
        self.assertEqual(result["data"][0]["title"], "Source title")
        self.assertEqual(
            result["data"][0]["tags"],
            f"2 - {MCPTranslationTag._meta.verbose_name_plural}",
        )

    def test_fetch_and_update_translation_components(self):
        detail = self.tools.fetch_detail(self.view_id, str(self.article.pk))
        source_name = f"{self.translation_table}:en"
        german_name = f"{self.translation_table}:de"
        french_name = f"{self.translation_table}:fr"

        self.assertEqual(
            set(detail["components"]),
            {source_name, german_name, french_name},
        )
        self.assertTrue(
            detail["components"][source_name]["fields"]["title"]["readonly"]
        )
        self.assertFalse(
            detail["components"][german_name]["fields"]["title"]["readonly"]
        )
        self.assertEqual(
            detail["components"][german_name]["fields"]["title"]["value"],
            "German title",
        )
        with self.assertRaises(LookupError):
            self.tools.update_detail(
                self.view_id,
                str(self.article.pk),
                component_values={source_name: {"title": "Changed source"}},
            )

        result = self.tools.update_detail(
            self.view_id,
            str(self.article.pk),
            component_values={
                german_name: {
                    "title": "Updated German title",
                    "tags": [self.first_tag.pk],
                },
                french_name: {
                    "title": "French title",
                    "slug": "french-title",
                },
            },
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            MCPTranslatedArticleTranslation.objects.get(
                master=self.article, language_code="de"
            ).title,
            "Updated German title",
        )
        self.assertEqual(
            MCPTranslatedArticleTranslation.objects.get(
                master=self.article, language_code="fr"
            ).title,
            "French title",
        )
        self.assertEqual(
            MCPTranslatedArticleTranslation.objects.get(
                master=self.article, language_code="en"
            ).title,
            "Source title",
        )

    def test_update_translation_persists_many_to_many_fields(self):
        german_name = f"{self.translation_table}:de"

        result = self.tools.update_detail(
            self.view_id,
            str(self.article.pk),
            component_values={
                german_name: {
                    "tags": [self.second_tag.pk],
                }
            },
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            list(self.german_translation.tags.values_list("pk", flat=True)),
            [self.second_tag.pk],
        )

    def test_many_to_many_translation_status_does_not_duplicate_list_rows(self):
        english_translation = MCPTranslatedArticleTranslation.objects.get(
            master=self.article,
            language_code="en",
        )
        english_translation.tags.set([self.first_tag, self.second_tag])
        self.german_translation.tags.set([self.first_tag, self.second_tag])
        result = self.tools.list_rows(
            view_id=self.view_id,
            fields=["title"],
            page_size=1,
        )

        self.assertEqual(result["last_row"], 1)
        self.assertEqual(result["last_page"], 1)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["title"], "Source title")

    def test_browser_detail_uses_shared_translation_forms(self):
        request = self.tools.request
        view = request.request_data.configuration.view_map[self.view_id]
        german = MCPTranslatedArticleTranslation.objects.get(
            master=self.article, language_code="de"
        )
        bind_sbadmin_request_data(
            request,
            view=self.view_id,
            action="detail",
            modifier="template",
            object_id=str(self.article.pk),
            method="POST",
            post={
                "id": str(german.pk),
                "language_code": "de",
                TRANSLATION_MODEL_KEY: self.translation_table,
                "title": "Browser-updated title",
                "slug": "browser-updated-title",
            },
        )

        view.detail(request, "template", object_id=str(self.article.pk))

        german.refresh_from_db()
        self.assertEqual(german.title, "Browser-updated title")
