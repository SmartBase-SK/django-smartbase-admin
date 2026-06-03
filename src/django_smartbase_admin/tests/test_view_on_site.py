"""Smoke test for the stock Django ``r/<ct>/<id>/`` shadow.

SBAdmin ships ``ViewOnSiteRedirectView`` as the only gated entry point that
honors ``restrict_queryset`` / ``has_view_permission`` (see
``views/view_on_site_redirect_view.py``). The stock Django
``r/<int:content_type_id>/<path:object_id>/`` view (named
``admin:view_on_site``) bypasses both and is inherited via
``super().get_urls()``, so ``SBAdminSite._stock_admin_endpoint_404`` shadows
it. This test pins that wiring — if anyone reorders ``get_urls`` so the
stock route is reachable again, it fails.
"""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import path, resolve, reverse

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import SBAdminSite, sb_admin_site
from django_smartbase_admin.engine.admin_entrypoint_view import SBAdminEntrypointView

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(ROOT_URLCONF=__name__)
class StockViewOnSiteShadowTest(TestCase):
    def test_stock_view_on_site_route_resolves_to_404_handler(self):
        url = reverse("sb_admin:view_on_site", args=(1, 1))
        match = resolve(url)
        self.assertIs(match.func, SBAdminSite._stock_admin_endpoint_404)


class SBAdminUrlOrderingTest(TestCase):
    def test_final_catch_all_view_stays_enabled(self):
        self.assertIs(SBAdminSite.final_catch_all_view, True)

    def test_stock_catch_all_is_last_pattern(self):
        patterns = sb_admin_site.get_urls()
        stock_urls, catch_all_urls = sb_admin_site._split_stock_admin_urls()
        self.assertEqual(len(catch_all_urls), 1)
        self.assertIs(patterns[-1], catch_all_urls[0])


@override_settings(ROOT_URLCONF=__name__, APPEND_SLASH=True)
class ModelChangeUrlRoutingTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from filer.models import Folder

        if not sb_admin_site.is_registered(Folder):

            class FolderAdmin(SBAdmin):
                model = Folder
                list_display = ("id",)

            sb_admin_site.register(Folder, FolderAdmin)
        cls.admin = sb_admin_site._registry[Folder]
        cls.change_url = reverse(
            f"sb_admin:{cls.admin.get_id()}_change",
            kwargs={"object_id": "1"},
        )

    def test_change_url_with_trailing_slash_resolves_to_model_admin(self):
        match = resolve(self.change_url)
        self.assertNotEqual(match.func, SBAdminEntrypointView.as_view())
        self.assertNotEqual(match.kwargs.get("object_id"), "change")

    def test_change_url_without_trailing_slash_redirects_to_slash_version(self):
        self.assertTrue(self.change_url.endswith("/"))
        bare_url = self.change_url.rstrip("/")
        response = self.client.get(bare_url)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], self.change_url)

    def test_sbadmin_action_url_resolves_after_model_urls(self):
        action_url = reverse(
            "sb_admin:sb_admin_base",
            kwargs={
                "view": self.admin.get_id(),
                "action": "action_list_json",
                "modifier": "template",
            },
        )
        match = resolve(action_url)
        self.assertEqual(match.func, SBAdminEntrypointView.as_view())
        self.assertEqual(match.kwargs["view"], self.admin.get_id())
        self.assertEqual(match.kwargs["action"], "action_list_json")
