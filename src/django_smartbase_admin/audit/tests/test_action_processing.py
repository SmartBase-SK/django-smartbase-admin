"""High-level tests for SBAdmin action processing and row action rendering."""

from types import SimpleNamespace
from unittest.mock import patch

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, TestCase
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.actions.admin_action_list import SBAdminListAction
from django_smartbase_admin.engine.actions import (
    SBAdminCustomAction,
    SBAdminFormViewAction,
    SBAdminRowAction,
)
from django_smartbase_admin.engine.admin_base_view import (
    SBAdminBaseListView,
    SBAdminBaseView,
)
from django_smartbase_admin.engine.const import (
    IGNORE_LIST_SELECTION,
    MODIFIER_OBJECT_ID,
)
from django_smartbase_admin.engine.modal_view import (
    ActionModalView,
    RowActionModalView,
    SBAdminActionError,
)
from django_smartbase_admin.plugins.nested import (
    CHILDREN_FIELD,
    CHILDREN_IDS,
    LAST_CHILD_FIELD,
    PARENT_REAL_ID,
    TabulatorNestedPlugin,
)


class PublishArticleView(RowActionModalView):
    form_class = forms.Form


class FakeAdminView(SBAdminBaseView):
    def __init__(self, row_actions=None, has_action_permission=True):
        self.row_actions = row_actions or []
        self.has_action_permission = has_action_permission

    def get_action_url(self, action, modifier="template", object_id=None):
        url = f"/actions/{action}/{modifier}/"
        if object_id is not None:
            url = f"{url}{object_id}/"
        return url

    def has_permission_for_action(self, request, action):
        return self.has_action_permission

    def get_sbadmin_row_actions_processed(self, request):
        return self.process_row_actions(request, self.row_actions)

    def get_context_data(self, request):
        return {}

    def get_tabulator_definition(self, request):
        return {}

    def get_config_data(self, request):
        return {}

    def get_filters_template_name(self, request):
        return ""

    def get_tabulator_header_template_name(self, request):
        return ""

    def get_search_fields(self, request):
        return []

    def get_search_field_placeholder(self, request):
        return ""

    def get_config_url(self, request):
        return ""

    def has_add_permission(self, request):
        return False

    def get_sbadmin_list_actions_processed(self, request):
        return []

    def get_sbadmin_list_selection_actions_grouped(self, request):
        return []


class TestListAction(SBAdminListAction):
    def __init__(self, view, request):
        self.view = view
        self.threadsafe_request = request
        self.column_fields = []
        self.tabulator_definition = {}
        self.list_actions = None
        self.advanced_filter_data = {}
        self.columns_data = {}
        self.allowed_framework_keys = {
            "_row_actions",
            "_children",
            "_sbadmin_tree_last_child",
        }

    def get_pk_field(self):
        return SimpleNamespace(name="id")

    def get_filters(self):
        return []

    def get_tabulator_columns_add_id_column_if_missing(self, add_id_column=True):
        return [], "id"


class TestNestedListAction(TestListAction):
    def process_final_data(self, final_data):
        pass


class RowList:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def __iter__(self):
        return iter(self.rows)


class RowActionIntegrationTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def test_permission_gated_target_view_row_action_is_materialized(self):
        class ArticleAdmin(FakeAdminView, SBAdminBaseListView):
            def get_sbadmin_row_actions(self, request):
                if not request.user.has_perm("blog.publish_article"):
                    return []
                return [
                    SBAdminRowAction(
                        target_view=PublishArticleView,
                        title=_("Publish"),
                        icon="Check-correct",
                        view=self,
                    )
                ]

            def get_sbadmin_row_actions_processed(self, request):
                return self.process_row_actions(
                    request, self.get_sbadmin_row_actions(request)
                )

        allowed_request = RequestFactory().get("/")
        allowed_request.user = SimpleNamespace(
            has_perm=lambda perm: perm == "blog.publish_article"
        )
        denied_request = RequestFactory().get("/")
        denied_request.user = SimpleNamespace(has_perm=lambda perm: False)

        view = ArticleAdmin()
        view.init_actions(denied_request)
        view.init_actions(allowed_request)

        allowed_first_view = ArticleAdmin()
        allowed_first_view.init_actions(allowed_request)
        denied_context = TestListAction(
            allowed_first_view, denied_request
        ).get_template_data()

        self.assertTrue(hasattr(view, "PublishArticleView"))
        self.assertNotIn(
            "_row_actions",
            [
                column["field"]
                for column in denied_context["tabulator_definition"]["tableColumns"]
            ],
        )

    def test_row_actions_are_processed_into_table_column_and_row_descriptors(self):
        view = FakeAdminView()
        view.row_actions = [
            SBAdminRowAction(
                target_view=PublishArticleView,
                title=lambda row: f"Publish {row['title']}",
                icon="Check-correct",
                view=view,
                enabled_field="status",
                enabled_value="draft",
            ),
            SBAdminRowAction(
                action_id="action_archive_article",
                title="Archive",
                icon="Delete",
                css_class=lambda row: f"btn-icon {row['status']}",
                view=view,
                enabled_if=lambda row: row.get("status") != "archived",
            ),
            SBAdminRowAction(
                url="/articles/__object_id__/",
                title="Open",
                icon="Preview-open",
                open_in_new_tab=True,
            ),
        ]

        list_action = TestListAction(view, self.request)
        context = list_action.get_template_data()
        rows = [
            {"id": 7, "title": "Draft Article", "status": "Draft"},
            {"id": 8, "title": "Archived Article", "status": "Archived"},
        ]
        raw_rows_by_pk = {
            7: {"id": 7, "title": "Draft Article", "status": "draft"},
            8: {"id": 8, "title": "Archived Article", "status": "archived"},
        }

        list_action.inject_row_actions(rows, raw_rows_by_pk=raw_rows_by_pk)

        self.assertEqual(
            context["tabulator_definition"]["tableColumns"][0]["formatter"],
            "sbadminRowActionsFormatter",
        )
        self.assertTrue(
            context["tabulator_definition"]["tableColumns"][0]["sbadminSystemColumn"]
        )
        self.assertEqual(
            rows[0]["_row_actions"],
            [
                {
                    "url": "/actions/PublishArticleView/template/7/",
                    "title": "Publish Draft Article",
                    "icon": "Check-correct",
                    "css_class": "btn btn-small btn-only-icon",
                    "open_in_modal": True,
                    "is_method_action": False,
                    "open_in_new_tab": False,
                },
                {
                    "url": "/actions/action_archive_article/template/7/",
                    "title": "Archive",
                    "icon": "Delete",
                    "css_class": "btn-icon draft",
                    "open_in_modal": False,
                    "is_method_action": True,
                    "open_in_new_tab": False,
                },
                {
                    "url": "/articles/7/",
                    "title": "Open",
                    "icon": "Preview-open",
                    "css_class": "btn btn-small btn-only-icon",
                    "open_in_modal": False,
                    "is_method_action": False,
                    "open_in_new_tab": True,
                },
            ],
        )
        self.assertEqual(
            [descriptor["url"] for descriptor in rows[1]["_row_actions"]],
            ["/articles/8/"],
        )

    def test_nested_plugin_materializes_row_actions_for_child_rows(self):
        request = RequestFactory().get("/")
        request.request_data = SimpleNamespace(additional_data={})
        view = FakeAdminView()
        view.row_actions = [
            SBAdminRowAction(
                action_id="action_archive_article",
                title="Archive",
                icon="Delete",
                view=view,
            )
        ]
        action = TestNestedListAction(view, request)
        store = TabulatorNestedPlugin.get_request_data_plugin_store(request)
        store["base_qs"] = RowList(
            [
                {"id": 1, "parent": None},
                {"id": 2, "parent": 1},
            ]
        )

        with patch(
            "django_smartbase_admin.plugins.nested.resolve_nested",
            return_value={"parent_field": "parent"},
        ):
            result = TabulatorNestedPlugin.modify_final_data(
                action,
                request=request,
                data=[{PARENT_REAL_ID: 1, CHILDREN_IDS: [1, 2]}],
            )

        self.assertEqual(
            result[0]["_row_actions"][0]["url"],
            "/actions/action_archive_article/template/1/",
        )
        child = result[0][CHILDREN_FIELD][0]
        self.assertEqual(
            child["_row_actions"][0]["url"],
            "/actions/action_archive_article/template/2/",
        )
        self.assertTrue(child[LAST_CHILD_FIELD])

    def test_detail_actions_materialize_current_object_without_mutating_row_action(
        self,
    ):
        view = FakeAdminView()
        action = SBAdminRowAction(
            target_view=PublishArticleView,
            title="Publish",
            icon="Check-correct",
            view=view,
        )

        processed = view.process_detail_actions(self.request, [action], object_id=123)
        processed_without_object = view.process_detail_actions(
            self.request, [action], object_id=None
        )

        self.assertEqual(action.action_modifier, MODIFIER_OBJECT_ID)
        self.assertEqual(processed[0].url, "/actions/PublishArticleView/template/123/")
        self.assertEqual(
            processed_without_object[0].url,
            f"/actions/PublishArticleView/{IGNORE_LIST_SELECTION}/",
        )

    def test_detail_action_without_object_modifier_keeps_template_modifier(self):
        view = FakeAdminView()
        action = SBAdminCustomAction(
            title="Contact",
            view=view,
            action_id="contact",
        )

        processed = view.process_detail_actions(self.request, [action], object_id=123)

        self.assertEqual(processed[0].url, "/actions/contact/template/")

    def test_detail_row_modal_action_infers_current_object(self):
        view = FakeAdminView()
        action = SBAdminFormViewAction(
            target_view=PublishArticleView,
            title="Publish",
            view=view,
        )

        processed = view.process_detail_actions(self.request, [action], object_id=123)

        self.assertEqual(processed[0].url, "/actions/PublishArticleView/template/123/")

    def test_form_view_actions_are_registered_before_permission_filtering(self):
        view = FakeAdminView(has_action_permission=False)
        action = SBAdminFormViewAction(
            target_view=PublishArticleView,
            title="Publish",
            view=view,
        )

        processed = view.process_list_actions(self.request, [action])

        self.assertEqual(processed, [])
        self.assertTrue(hasattr(view, "PublishArticleView"))
        self.assertIsNone(action.url)

    def test_form_view_action_uses_declared_action_id(self):
        class CustomActionIdView(RowActionModalView):
            action_id = "custom_action_id"
            form_class = forms.Form

        view = FakeAdminView()
        action = SBAdminFormViewAction(
            target_view=CustomActionIdView,
            title="Publish",
            view=view,
        )

        processed = view.process_list_actions(self.request, [action])

        self.assertTrue(hasattr(view, "custom_action_id"))
        self.assertEqual(processed[0].action_id, "custom_action_id")
        self.assertEqual(processed[0].url, "/actions/custom_action_id/template/")
        self.assertIsNone(action.action_id)
        self.assertIsNone(action.url)

    def test_row_action_materializes_explicit_url_without_mutating_definition(self):
        view = FakeAdminView()
        action = SBAdminCustomAction(
            title="Open",
            url=f"/articles/{MODIFIER_OBJECT_ID}/",
            action_modifier=MODIFIER_OBJECT_ID,
        )

        processed = view.process_row_actions(self.request, [action])

        self.assertEqual(action.url, f"/articles/{MODIFIER_OBJECT_ID}/")
        self.assertEqual(processed[0].url, f"/articles/{MODIFIER_OBJECT_ID}/")

    def test_nested_form_view_actions_are_registered(self):
        view = FakeAdminView()
        parent = SBAdminCustomAction(
            title="Contact",
            view=view,
            action_id="contact",
            sub_actions=[
                SBAdminFormViewAction(
                    target_view=PublishArticleView,
                    title="Publish",
                    view=view,
                    action_modifier=MODIFIER_OBJECT_ID,
                )
            ],
        )

        processed = view.process_detail_actions(self.request, [parent], object_id=123)

        self.assertEqual(
            processed[0].sub_actions[0].url,
            "/actions/PublishArticleView/template/123/",
        )
        self.assertTrue(hasattr(view, "PublishArticleView"))

    def test_row_action_rejects_missing_or_ambiguous_interaction_modes(self):
        with self.assertRaises(ImproperlyConfigured):
            SBAdminRowAction(title="Broken", icon="Close")

        with self.assertRaises(ImproperlyConfigured):
            SBAdminRowAction(
                title="Broken",
                icon="Close",
                action_id="action_archive_article",
                url="/articles/__object_id__/",
            )


class ModalActionIntegrationTests(TestCase):
    def test_modal_action_errors_render_as_form_errors(self):
        class ErrorModal(ActionModalView):
            form_class = forms.Form

            def process_form_valid(self, request, form):
                raise SBAdminActionError("Cannot process this action.")

        response = ErrorModal.as_view(view=FakeAdminView())(RequestFactory().post("/"))

        self.assertEqual(
            response.context_data["form"].non_field_errors(),
            ["Cannot process this action."],
        )

    def test_row_modal_missing_object_returns_not_found(self):
        class MissingRowModal(RowActionModalView):
            form_class = forms.Form

            def get_object(self):
                return None

        response = MissingRowModal.as_view(view=FakeAdminView())(
            RequestFactory().post("/"), modifier="123"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"Not found.")
