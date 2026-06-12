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
from django.test import RequestFactory, TestCase, override_settings
from django.urls import path, resolve, reverse

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import SBAdminSite, sb_admin_site
from django_smartbase_admin.engine.admin_entrypoint_view import SBAdminEntrypointView
from django_smartbase_admin.engine.const import SB_ADMIN_BACK_URL
from django_smartbase_admin.services.views import SBAdminViewService

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


@override_settings(ROOT_URLCONF=__name__)
class NavigationReturnToTest(TestCase):
    """``SBAdminViewService`` back_url resolution. Validation relies on
    ``resolve()`` recognising the ``sb_admin`` namespace, so the module-level
    ``urlpatterns`` mounting the admin site applies. ``sb_admin:login`` is a
    stable, resolvable in-namespace URL used as the valid return target."""

    def setUp(self):
        self.factory = RequestFactory()
        self.admin_url = reverse("sb_admin:login")
        self.default_url = "/sb-admin/default-changelist/"
        self.current_path = "/sb-admin/current/"

    def test_validate_accepts_in_namespace_url(self):
        request = self.factory.get(self.current_path)
        self.assertTrue(SBAdminViewService.validate_back_url(request, self.admin_url))

    def test_validate_rejects_external_host(self):
        request = self.factory.get(self.current_path)
        self.assertFalse(
            SBAdminViewService.validate_back_url(
                request, "https://evil.example.com/sb-admin/login/"
            )
        )

    def test_validate_rejects_non_sb_admin_path(self):
        request = self.factory.get(self.current_path)
        self.assertFalse(
            SBAdminViewService.validate_back_url(request, "/some/other/page/")
        )

    def test_validate_rejects_self_loop(self):
        request = self.factory.get(self.admin_url)
        self.assertFalse(
            SBAdminViewService.validate_back_url(
                request, self.admin_url, current_path=self.admin_url
            )
        )

    def test_validate_rejects_empty(self):
        request = self.factory.get(self.current_path)
        self.assertFalse(SBAdminViewService.validate_back_url(request, None))
        self.assertFalse(SBAdminViewService.validate_back_url(request, ""))

    def test_resolve_prefers_post_over_get(self):
        request = self.factory.post(
            self.current_path, data={SB_ADMIN_BACK_URL: self.admin_url}
        )
        request.GET = request.GET.copy()
        request.GET[SB_ADMIN_BACK_URL] = "/sb-admin/from-get/"
        self.assertEqual(
            SBAdminViewService.resolve_back_url(
                request, self.default_url, current_path=self.current_path
            ),
            self.admin_url,
        )

    def test_resolve_uses_get_when_no_post(self):
        request = self.factory.get(
            self.current_path, data={SB_ADMIN_BACK_URL: self.admin_url}
        )
        self.assertEqual(
            SBAdminViewService.resolve_back_url(
                request, self.default_url, current_path=self.current_path
            ),
            self.admin_url,
        )

    def test_resolve_ignores_referer_entirely(self):
        request = self.factory.get(self.current_path)
        request.META["HTTP_REFERER"] = self.admin_url
        self.assertEqual(
            SBAdminViewService.resolve_back_url(
                request, self.default_url, current_path=self.current_path
            ),
            self.default_url,
        )

    def test_resolve_falls_back_to_default_when_no_param(self):
        request = self.factory.post(self.current_path)
        self.assertEqual(
            SBAdminViewService.resolve_back_url(
                request, self.default_url, current_path=self.current_path
            ),
            self.default_url,
        )

    def test_append_back_url_no_existing_query(self):
        self.assertEqual(
            SBAdminViewService.append_back_url("/sb-admin/x/", "/sb-admin/y/"),
            "/sb-admin/x/?back_url=%2Fsb-admin%2Fy%2F",
        )

    def test_append_back_url_preserves_other_query_and_replaces_existing(self):
        result = SBAdminViewService.append_back_url(
            "/sb-admin/x/?a=1&back_url=/old/", "/sb-admin/new/"
        )
        self.assertIn("a=1", result)
        self.assertIn("back_url=%2Fsb-admin%2Fnew%2F", result)
        self.assertNotIn("%2Fold%2F", result)

    def test_append_back_url_noop_when_empty(self):
        self.assertEqual(
            SBAdminViewService.append_back_url("/sb-admin/x/", None),
            "/sb-admin/x/",
        )

    def test_url_with_current_back_url(self):
        request = self.factory.get("/sb-admin/source/?page=2")
        result = SBAdminViewService.url_with_current_back_url(
            request, "/sb-admin/target/"
        )
        self.assertEqual(
            result,
            "/sb-admin/target/?back_url=%2Fsb-admin%2Fsource%2F%3Fpage%3D2",
        )

    def test_keep_back_url_carries_param_from_request(self):
        request = self.factory.get(
            "/sb-admin/x/", data={SB_ADMIN_BACK_URL: "/sb-admin/origin/"}
        )
        result = SBAdminViewService.keep_back_url(request, "/sb-admin/detail/")
        self.assertEqual(result, "/sb-admin/detail/?back_url=%2Fsb-admin%2Forigin%2F")

    def test_keep_back_url_noop_without_param(self):
        request = self.factory.get("/sb-admin/x/")
        self.assertEqual(
            SBAdminViewService.keep_back_url(request, "/sb-admin/detail/"),
            "/sb-admin/detail/",
        )
