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

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import path, resolve, reverse

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import SBAdminSite, sb_admin_site
from django_smartbase_admin.engine.admin_entrypoint_view import SBAdminEntrypointView

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


def _unwrapped_func(match):
    func = match.func
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


def _resolved_view_class(match):
    func = _unwrapped_func(match)
    return getattr(func, "view_class", None) or getattr(func, "cls", None)


@override_settings(ROOT_URLCONF=__name__)
class StockViewOnSiteShadowTest(TestCase):
    def test_stock_view_on_site_route_resolves_to_404_handler(self):
        url = reverse("sb_admin:view_on_site", args=(1, 1))
        match = resolve(url)
        self.assertIs(match.func, SBAdminSite._stock_admin_endpoint_404)


class SBAdminUrlOrderingTest(TestCase):
    def test_final_catch_all_disabled_on_site_class(self):
        self.assertIs(SBAdminSite.final_catch_all_view, False)

    def test_super_get_urls_has_no_catch_all(self):
        from django.contrib.admin.sites import AdminSite

        site = SBAdminSite(name="sb_admin_test")
        site.final_catch_all_view = True
        with_catch_all = len(AdminSite.get_urls(site))
        site.final_catch_all_view = False
        without_catch_all = len(AdminSite.get_urls(site))
        self.assertEqual(with_catch_all, without_catch_all + 1)

    def test_manual_catch_all_is_last_pattern(self):
        patterns = sb_admin_site.get_urls()
        self.assertRegex(str(patterns[-1].pattern), r"\(\?P<url>")


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

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="sbadmin_url_test",
            email="sbadmin_url_test@example.com",
            password="password",
        )
        self.client.force_login(self.user)

    def test_change_url_with_trailing_slash_resolves_to_model_admin(self):
        match = resolve(self.change_url)
        self.assertIsNot(_resolved_view_class(match), SBAdminEntrypointView)
        self.assertEqual(match.url_name, f"{self.admin.get_id()}_change")

    def test_change_url_without_trailing_slash_redirects_to_slash_version(self):
        self.assertTrue(self.change_url.endswith("/"))
        bare_url = self.change_url.rstrip("/")
        match = resolve(bare_url)
        resolved = _unwrapped_func(match)
        underlying = getattr(resolved, "__func__", resolved)
        self.assertEqual(underlying.__name__, "catch_all_view")
        self.assertIsNot(_resolved_view_class(match), SBAdminEntrypointView)
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
        self.assertIs(_resolved_view_class(match), SBAdminEntrypointView)
        self.assertEqual(match.kwargs["view"], self.admin.get_id())
        self.assertEqual(match.kwargs["action"], "action_list_json")
