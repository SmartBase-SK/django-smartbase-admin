from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration
from django_smartbase_admin.engine.quick_search import (
    QuickSearchService,
    normalize_text,
    search_terms,
    text_rank,
)
from django_smartbase_admin.views.quick_search_view import QuickSearchView


class FakeView:
    def __init__(self, view_id, *, add=True, add_url="/add/", add_label=None):
        self.view_id = view_id
        self.add = add
        self.add_url = add_url
        self.add_label = add_label
        self.model = SimpleNamespace(
            _meta=SimpleNamespace(verbose_name=f"{view_id} item")
        )

    def get_id(self):
        return self.view_id

    def has_add_permission(self, request):
        return self.add

    def get_new_url(self, request):
        return self.add_url

    def get_add_label(self, request, object_id=None):
        return self.add_label


def menu(label, url="", view_id=None, icon=None, sub_items=None):
    return {
        "get_label": label,
        "get_url": url,
        "get_view_id": view_id,
        "get_icon": icon,
        "sub_items": sub_items or [],
    }


def fake_request(menu_items, view_map, enabled=True):
    configuration = SimpleNamespace(
        view_map=view_map,
        is_quick_search_enabled=lambda request: enabled,
    )
    request = RequestFactory().get("/quick-search/")
    request.request_data = SimpleNamespace(
        configuration=configuration, menu_items=menu_items
    )
    return request


class TextHelpersTest(SimpleTestCase):
    def test_normalize_ignores_case_and_diacritics(self):
        self.assertEqual(normalize_text("Tržby ŽSSK"), "trzby zssk")

    def test_search_terms_keep_quoted_phrases(self):
        self.assertEqual(search_terms('"fact sale" dwh'), ["fact sale", "dwh"])

    def test_rank_prefers_exact_then_prefix_and_needs_every_term(self):
        self.assertEqual(text_rank("Tržby", ["trzby"]), 0)
        self.assertEqual(text_rank("Tržby mesačne", ["trzby"]), 1)
        self.assertEqual(text_rank("Mesačné tržby", ["trzby"]), 2)
        self.assertIsNone(text_rank("Mesačné tržby", ["trzby", "rocne"]))


class QuickSearchServiceTest(SimpleTestCase):
    def setUp(self):
        self.products = FakeView("products", add_label="product")
        self.vouchers = FakeView("vouchers")
        self.settings = FakeView("settings", add=False)
        self.menu_items = [
            menu(
                "Catalog",
                icon="Box",
                sub_items=[
                    menu("Products", "/products/", "products"),
                    menu("Gift vouchers", "/vouchers/", "vouchers"),
                ],
            ),
            menu("Settings", "/settings/", "settings", icon="Setting-two"),
            menu("Hidden", "", "settings"),
        ]
        self.view_map = {
            "products": self.products,
            "vouchers": self.vouchers,
            "settings": self.settings,
        }

    def search(self, term):
        request = fake_request(self.menu_items, self.view_map)
        return {
            section["key"]: section["items"]
            for section in QuickSearchService(request).search(term)
        }

    def test_pages_follow_the_menu_with_breadcrumbs(self):
        pages = self.search("vouch")["pages"]
        self.assertEqual(pages[0]["title"], "Gift vouchers")
        self.assertEqual(pages[0]["description"], "Catalog")
        self.assertEqual(pages[0]["url"], "/vouchers/")
        self.assertEqual(pages[0]["icon"], "Box")

    def test_pages_without_url_are_not_offered(self):
        titles = [page["title"] for page in self.search("")["pages"]]
        self.assertNotIn("Hidden", titles)
        self.assertEqual(titles, ["Products", "Gift vouchers", "Settings"])

    def test_add_actions_are_sorted_by_name_not_by_add_prefix(self):
        self.vouchers.add_label = None
        self.products.add_label = "zebra product"
        titles = [a["title"] for a in self.search("")["actions"]]
        self.assertEqual(titles, ["Add: vouchers item", "Add zebra product"])

    def test_add_actions_need_add_permission(self):
        actions = self.search("")["actions"]
        self.assertEqual(
            [(a["title"], a["url"]) for a in actions],
            [("Add product", "/add/"), ("Add: vouchers item", "/add/")],
        )
        self.assertEqual(actions[0]["description"], "Catalog / Products")

    def test_matching_ignores_diacritics_and_needs_every_term(self):
        self.menu_items[0]["sub_items"][0]["get_label"] = "Produkty"
        result = self.search("produkty catalog")
        self.assertEqual([p["title"] for p in result["pages"]], ["Produkty"])
        self.assertNotIn("actions", self.search("nothing like this"))

    def test_records_are_skipped_for_short_terms(self):
        searched = []
        self.products.has_quick_search = lambda request: True
        self.products.get_quick_search_items = (
            lambda request, term: searched.append(term) or []
        )
        self.search("pr")
        self.search("pro")
        self.assertEqual(searched, ["pro"])

    def test_record_sections_are_titled_by_the_menu_item(self):
        from django_smartbase_admin.engine.quick_search import QuickSearchItem

        self.products.has_quick_search = lambda request: True
        self.products.get_quick_search_section_title = lambda request: None
        self.products.get_quick_search_items = lambda request, term: [
            QuickSearchItem(title="Phone", url="/products/1/")
        ]
        request = fake_request(self.menu_items, self.view_map)
        sections = QuickSearchService(request).search("phone")
        self.assertEqual(sections[-1]["title"], "Products")
        self.assertEqual(sections[-1]["items"][0]["title"], "Phone")

    def test_failing_admin_does_not_break_the_search(self):
        def boom(request, term):
            raise RuntimeError("broken admin")

        self.products.has_quick_search = lambda request: True
        self.products.get_quick_search_items = boom
        with self.assertLogs("django_smartbase_admin.engine.quick_search", "ERROR"):
            result = self.search("products")
        self.assertIn("pages", result)


class QuickSearchViewTest(SimpleTestCase):
    def test_json_response_and_disabled_configuration(self):
        request = fake_request([menu("Products", "/p/", None)], {})
        request.GET = {"q": "prod"}
        response = QuickSearchView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"title": "Products"', response.content)

        from django.http import Http404

        disabled = fake_request([], {}, enabled=False)
        with self.assertRaises(Http404):
            QuickSearchView.as_view()(disabled)


class UserQuickSearchAdmin(SBAdmin):
    sbadmin_quick_search_fields = ["username", "email"]
    sbadmin_quick_search_limit = 2

    def get_queryset(self, request=None):
        return get_user_model().objects.order_by("username")

    def has_view_permission(self, request, obj=None):
        return True

    def get_detail_url(self, object_id=None):
        return f"/users/{object_id}/"

    def get_quick_search_description(self, request, obj):
        return obj.email


class RecordSearchTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        for username, email in [
            ("anna", "anna@example.com"),
            ("annabel", "bel@example.com"),
            ("hanna", "hanna@example.com"),
            ("peter", "anna.fan@example.com"),
        ]:
            user_model.objects.create(username=username, email=email)

    def setUp(self):
        self.admin = UserQuickSearchAdmin(get_user_model(), sb_admin_site)
        self.request = RequestFactory().get("/")

    def titles(self, term):
        return [
            item.title for item in self.admin.get_quick_search_items(self.request, term)
        ]

    def test_exact_match_first_then_prefix_and_limit(self):
        self.assertEqual(self.titles("anna"), ["anna", "annabel"])

    def test_every_term_must_match_one_of_the_fields(self):
        self.admin.sbadmin_quick_search_limit = 5
        self.assertEqual(self.titles("anna fan"), ["peter"])

    def test_item_payload(self):
        item = self.admin.get_quick_search_items(self.request, "hanna")[0]
        self.assertEqual(item.description, "hanna@example.com")
        self.assertTrue(item.url.startswith("/users/"))
        self.assertEqual(item.icon, "Box")

    def test_admin_without_fields_does_not_search(self):
        self.admin.sbadmin_quick_search_fields = None
        self.assertFalse(self.admin.has_quick_search(self.request))


class FallbackOnConfiguration(SBAdminRoleConfiguration):
    quick_search_use_search_fields = True


class FallbackOffConfiguration(SBAdminRoleConfiguration):
    quick_search_use_search_fields = False


class UserListSearchAdmin(SBAdmin):
    list_display = ("username", "email")
    search_fields = ["username", "email"]
    sbadmin_quick_search_limit = 5

    def get_queryset(self, request=None):
        return get_user_model().objects.order_by("username")

    def has_view_permission(self, request, obj=None):
        return True

    def get_detail_url(self, object_id=None):
        return f"/users/{object_id}/"


class ListSearchFallbackTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        user_model.objects.create(username="zuzana", email="zuzana@example.com")
        user_model.objects.create(username="peter", email="zuza.fan@example.com")
        user_model.objects.create(username="jan", email="jan@example.com")

    def setUp(self):
        self.admin = UserListSearchAdmin(get_user_model(), sb_admin_site)

    def request(self, use_search_fields=True):
        request = RequestFactory().get("/")
        request.user = get_user_model()(is_superuser=True, is_staff=True)
        configuration = (
            FallbackOnConfiguration()
            if use_search_fields
            else FallbackOffConfiguration()
        )
        request.request_data = SimpleNamespace(
            configuration=configuration,
            request_get={},
            request_post={},
            request_method="GET",
            global_filter={},
            selected_view=None,
            object_id=None,
        )
        return request

    def test_search_fields_are_used_by_default(self):
        request = self.request()
        self.assertTrue(self.admin.has_quick_search(request))
        titles = [
            item.title for item in self.admin.get_quick_search_items(request, "zuza")
        ]
        self.assertEqual(titles, ["peter", "zuzana"])

    def test_configuration_can_turn_the_fallback_off(self):
        self.assertFalse(self.admin.has_quick_search(self.request(False)))

    def test_admin_can_opt_in_or_out(self):
        self.admin.sbadmin_quick_search = True
        self.assertTrue(self.admin.has_quick_search(self.request(False)))
        self.admin.sbadmin_quick_search = False
        self.assertFalse(self.admin.has_quick_search(self.request()))
