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

from django_smartbase_admin.admin.site import SBAdminSite, sb_admin_site

urlpatterns = [path("sb-admin/", sb_admin_site.urls)]


@override_settings(ROOT_URLCONF=__name__)
class StockViewOnSiteShadowTest(TestCase):
    def test_stock_view_on_site_route_resolves_to_404_handler(self):
        url = reverse("sb_admin:view_on_site", args=(1, 1))
        match = resolve(url)
        self.assertIs(match.func, SBAdminSite._stock_admin_endpoint_404)
