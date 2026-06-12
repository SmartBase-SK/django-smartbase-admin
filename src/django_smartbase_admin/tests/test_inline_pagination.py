from django.apps import apps
from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

if not settings.configured:
    settings.configure(
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
        INSTALLED_APPS=["django.contrib.contenttypes"],
        SECRET_KEY="test",
    )

if not apps.ready:
    import django

    django.setup()

from django_smartbase_admin.engine.inline_pagination import (
    InlinePaginated,
    PaginationFormSetBase,
    get_inline_admin_formset_by_prefix,
    get_inline_partial_prefix,
    resolve_search_fields_from_inline_table,
    resolve_search_lookups_for_model_field,
)
from django_smartbase_admin.templatetags.sb_paginated_inline import (
    build_tabulator_style_page_items,
    hx_vals,
    modify_pagination_path,
)


def _page_numbers(items):
    return [item["number"] for item in items if item["kind"] == "page"]


class BuildTabulatorStylePageItemsTests(SimpleTestCase):
    def test_shows_all_pages_when_within_active_range(self):
        items = build_tabulator_style_page_items(current_page=2, max_page=6)
        self.assertEqual(_page_numbers(items), [1, 2, 3, 4, 5, 6])

    def test_start_shows_first_active_range_and_last_page(self):
        items = build_tabulator_style_page_items(current_page=2, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 2, 3, 4, 5, 20])
        self.assertEqual(sum(item["kind"] == "ellipsis" for item in items), 1)

    def test_middle_shows_five_centered_pages(self):
        items = build_tabulator_style_page_items(current_page=10, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 8, 9, 10, 11, 12, 20])

    def test_end_shows_last_active_range_without_trailing_last_duplicate(self):
        items = build_tabulator_style_page_items(current_page=19, max_page=20)
        self.assertEqual(_page_numbers(items), [1, 16, 17, 18, 19, 20])
        self.assertEqual(sum(item["kind"] == "ellipsis" for item in items), 1)

    def test_at_most_five_numbered_buttons_in_middle(self):
        items = build_tabulator_style_page_items(current_page=10, max_page=50)
        page_items = [
            item
            for item in items
            if item["kind"] == "page" and item["number"] not in (1, 50)
        ]
        self.assertEqual(len(page_items), 5)


class InlinePaginationTests(SimpleTestCase):
    def test_modify_pagination_path_replaces_page_param(self):
        url = "/admin/app/model/1/change/?q=test&page=2#inline"
        self.assertEqual(modify_pagination_path(url, "page", 3), "q=test&page=3")

    def test_hx_vals_renders_inline_page_value(self):
        attrs = str(hx_vals("inline-page", 3))
        self.assertEqual(attrs, 'hx-vals=\'{"inline-page": "3"}\'')

    def test_page_num_uses_positive_get_param(self):
        formset = object.__new__(PaginationFormSetBase)
        formset.request = RequestFactory().get("/admin/?inline_page=4")
        formset.pagination_key = "inline_page"
        formset.prefix = "permissions"

        self.assertEqual(formset.get_page_num(), 4)

    def test_search_key_uses_inline_prefix(self):
        formset = object.__new__(PaginationFormSetBase)
        formset.prefix = "permissions"
        formset.search_key_suffix = "-q"

        self.assertEqual(formset.get_search_key(), "permissions-q")

    def test_search_term_uses_get_and_strips_value(self):
        formset = object.__new__(PaginationFormSetBase)
        formset.prefix = "permissions"
        formset.search_key_suffix = "-q"
        formset.request = RequestFactory().get("/admin/?permissions-q=%20Test%20")

        self.assertEqual(formset.get_search_term(), "Test")

    def test_search_term_falls_back_to_post(self):
        formset = object.__new__(PaginationFormSetBase)
        formset.prefix = "permissions"
        formset.search_key_suffix = "-q"
        formset.request = RequestFactory().post(
            "/admin/",
            data={"permissions-q": "Hello"},
        )

        self.assertEqual(formset.get_search_term(), "Hello")

    def test_default_search_fields_use_text_model_fields_without_inline(self):
        from django.contrib.contenttypes.models import ContentType

        formset = object.__new__(PaginationFormSetBase)
        formset.model = ContentType
        formset.inline_search_enabled = True
        formset.request = RequestFactory().get("/admin/")

        self.assertEqual(
            formset.get_search_fields(),
            ["app_label", "model"],
        )

    def test_search_fields_use_inline_table_columns(self):
        from django.contrib.contenttypes.models import ContentType

        class Inline:
            model = ContentType
            fields = ("app_label",)
            inline_search_fields = None

            def get_fields(self, request, obj=None):
                return self.fields

            def get_inline_search_fields(self, request, obj=None):
                return resolve_search_fields_from_inline_table(self, request, obj)

        inline = Inline()
        formset = object.__new__(PaginationFormSetBase)
        formset.model = ContentType
        formset.inline_search_enabled = True
        formset.inline_admin = inline
        formset.instance = None
        formset.request = RequestFactory().get("/admin/")

        self.assertEqual(formset.get_search_fields(), ["app_label"])

    def test_resolve_search_lookups_for_foreign_key_columns(self):
        from django.db import models

        class Related(models.Model):
            name = models.CharField(max_length=100)
            slug = models.SlugField(max_length=50)

            class Meta:
                app_label = "contenttypes"

        class Parent(models.Model):
            group = models.ForeignKey(Related, on_delete=models.CASCADE)

            class Meta:
                app_label = "contenttypes"

        self.assertEqual(
            resolve_search_lookups_for_model_field(Parent, "group"),
            ["group__name", "group__slug"],
        )
        self.assertEqual(
            resolve_search_lookups_for_model_field(Parent, "missing_method"),
            [],
        )

    def test_resolve_search_fields_from_inline_table_skips_row_class_field(self):
        from django.contrib.contenttypes.models import ContentType

        class Inline:
            model = ContentType
            fields = ("app_label", "get_sbadmin_row_class")

            def get_fields(self, request, obj=None):
                return self.fields

        self.assertEqual(
            resolve_search_fields_from_inline_table(
                Inline(), RequestFactory().get("/admin/")
            ),
            ["app_label"],
        )

    def test_filter_queryset_by_search_applies_distinct_for_related_lookups(self):
        class FakeQuerySet:
            def __init__(self):
                self.filter_args = None
                self.distinct_called = False

            def filter(self, *args, **kwargs):
                self.filter_args = (args, kwargs)
                return self

            def distinct(self):
                self.distinct_called = True
                return self

        formset = object.__new__(PaginationFormSetBase)
        formset.get_search_term = lambda: "abc"
        formset.get_search_fields = lambda: ["name", "author__name"]
        formset.get_search_lookup = lambda field_name, prefix="": (
            f"{field_name}__icontains"
        )

        queryset = FakeQuerySet()
        filtered = formset.filter_queryset_by_search(queryset)

        self.assertIs(filtered, queryset)
        self.assertIsNotNone(queryset.filter_args)
        self.assertTrue(queryset.distinct_called)

    def test_show_all_keeps_full_queryset(self):
        formset = object.__new__(PaginationFormSetBase)
        formset.queryset = [1, 2, 3]
        formset.request = RequestFactory().get("/admin/?all=1")
        formset.pagination_key = "page"
        formset.per_page = 1
        formset.prefix = "permissions"

        formset.mount_paginator()
        formset.mount_queryset()

        self.assertEqual(formset._queryset, [1, 2, 3])

    def test_inline_paginated_uses_explicit_formset_prefix(self):
        class BaseFormSet:
            @classmethod
            def get_default_prefix(cls):
                return "default-prefix"

        class ParentInline:
            def get_formset(self, request, obj=None, **kwargs):
                return BaseFormSet

        class TestInline(InlinePaginated, ParentInline):
            formset_prefix = "stable-prefix"

        formset_class = TestInline().get_formset(RequestFactory().get("/admin/"))

        self.assertEqual(formset_class.get_default_prefix(), "stable-prefix")

    def test_inline_partial_prefix_requires_htmx_request(self):
        request = RequestFactory().get(
            "/admin/",
            HTTP_X_SBADMIN_INLINE_PREFIX="prices",
        )

        self.assertIsNone(get_inline_partial_prefix(request))

    def test_inline_partial_prefix_uses_django_htmx_request_details(self):
        class HtmxRequestDetails:
            def __bool__(self):
                return True

        request = RequestFactory().get(
            "/admin/",
            HTTP_HX_REQUEST="true",
            HTTP_X_SBADMIN_INLINE_PREFIX="prices",
        )
        request.htmx = HtmxRequestDetails()

        self.assertEqual(get_inline_partial_prefix(request), "prices")

    def test_get_inline_admin_formset_by_prefix(self):
        class FormSet:
            prefix = "prices"

        class InlineAdminFormSet:
            formset = FormSet()

        context = {"inline_admin_formsets": [InlineAdminFormSet()]}

        self.assertIs(
            get_inline_admin_formset_by_prefix(context, "prices"),
            context["inline_admin_formsets"][0],
        )
        self.assertIsNone(get_inline_admin_formset_by_prefix(context, "other"))
