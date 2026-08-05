from pathlib import Path

import django_smartbase_admin
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django_smartbase_admin.engine.const import CONFIG_NAME, URL_PARAMS_NAME

PACKAGE_ROOT = Path(django_smartbase_admin.__file__).parent
SAVE_VIEW_BUTTON_CLASS = "js-save-view-button"

FULL_BAR_TEMPLATE = "sb_admin/config/view.html"
EMBEDDED_BAR_TEMPLATE = "sb_admin/config/view_embedded.html"

VIEW_ID = "demo_article"
OTHER_VIEW_ID = "demo_comment"


def _views_context(view_id=VIEW_ID):
    return {
        "view_id": view_id,
        "current_views": [
            {"name": "All", "url_params": "{}", "default": True},
            {"name": "Published", "url_params": '{"filterData": {}}', "default": True},
            {
                "id": 7,
                "name": "My rows",
                "url_params": '{"filterData": {}}',
                "detail_url": f"/{view_id}/config/7/",
            },
        ],
        "content_context": {
            "config_url": f"/{view_id}/config/",
            "const": {"CONFIG_NAME": CONFIG_NAME, "URL_PARAMS_NAME": URL_PARAMS_NAME},
        },
    }


class ViewsTemplateTestCase(SimpleTestCase):
    template_name = None

    def setUp(self):
        self.request = RequestFactory().get("/")

    def render(self, view_id=VIEW_ID):
        return render_to_string(
            self.template_name, _views_context(view_id), request=self.request
        )


class TestFullViewsBarTemplate(ViewsTemplateTestCase):
    """The bar list pages render: presets, the user's saved views and the save/delete affordances."""

    template_name = FULL_BAR_TEMPLATE

    def test_scopes_every_id_to_the_view(self):
        # More than one list table can live on a page; unprefixed ids would be shared.
        html = self.render()

        self.assertIn(f'id="{VIEW_ID}-views"', html)
        self.assertIn(f'id="{VIEW_ID}-view_form"', html)
        self.assertIn(f'id="{VIEW_ID}-save-view-modal"', html)
        self.assertIn(f'id="{VIEW_ID}-{URL_PARAMS_NAME}"', html)
        self.assertIn(f'form="{VIEW_ID}-view_form"', html)
        self.assertNotIn('id="view_form"', html)
        self.assertNotIn('id="save-view-modal"', html)
        self.assertNotIn(f'id="{URL_PARAMS_NAME}"', html)

    def test_renders_saved_views_with_delete(self):
        html = self.render()

        self.assertIn(">My rows<", html)
        self.assertIn(f'hx-delete="/{VIEW_ID}/config/7/"', html)

    def test_save_view_button_hides_itself_through_a_class_not_an_id(self):
        """The button is hidden while disabled (nothing to save yet) by CSS. Its id is prefixed per
        table, so the rule has to key off the class — an #id selector silently stops matching and
        the button then shows all the time."""
        components_css = (
            PACKAGE_ROOT / "static/sb_admin/src/css/_components.css"
        ).read_text()
        headers = [
            "sb_admin/actions/partials/tabulator_header_v1.html",
            "sb_admin/actions/partials/tabulator_header_v2.html",
        ]

        self.assertIn(f".{SAVE_VIEW_BUTTON_CLASS}", components_css)
        self.assertNotIn("#save-view-modal-button", components_css)
        for header in headers:
            markup = (PACKAGE_ROOT / "templates" / header).read_text()
            self.assertIn(SAVE_VIEW_BUTTON_CLASS, markup, header)
            self.assertIn("{{ view_id }}-save-view-modal-button", markup, header)

    def test_two_bars_on_one_page_do_not_share_ids(self):
        html = self.render() + self.render(view_id=OTHER_VIEW_ID)

        self.assertEqual(html.count(f'id="{VIEW_ID}-views"'), 1)
        self.assertEqual(html.count(f'id="{OTHER_VIEW_ID}-views"'), 1)
        self.assertEqual(html.count(f'id="{VIEW_ID}-save-view-modal"'), 1)
        self.assertEqual(html.count(f'id="{OTHER_VIEW_ID}-save-view-modal"'), 1)
        # openView is dispatched through the owning table instance, not a shared handler.
        self.assertIn(f"window.SBAdminTable['{VIEW_ID}']", html)
        self.assertIn(f"window.SBAdminTable['{OTHER_VIEW_ID}']", html)


class TestEmbeddedViewsBarTemplate(ViewsTemplateTestCase):
    """The bar an embedded list widget renders. It carries the same affordances as the full bar but
    no <form>: the widget sits inside the change form of the page it is embedded in, and a browser
    drops a nested form — taking the save and delete requests with it."""

    template_name = EMBEDDED_BAR_TEMPLATE

    def test_renders_no_form_and_no_form_associations(self):
        html = self.render()

        self.assertNotIn("<form", html)
        self.assertNotIn('form="', html)
        self.assertIn(f'id="{VIEW_ID}-views-bar"', html)

    def test_save_gathers_its_inputs_by_id_and_swaps_the_bar(self):
        # Without a form to serialise, htmx has to be told which inputs to send.
        html = self.render()
        name_input = f"#{VIEW_ID}-{CONFIG_NAME}"
        params_input = f"#{VIEW_ID}-{URL_PARAMS_NAME}"

        self.assertIn(f'id="{VIEW_ID}-{CONFIG_NAME}"', html)
        self.assertIn(f'id="{VIEW_ID}-{URL_PARAMS_NAME}"', html)
        self.assertIn(f'hx-include="{name_input}, {params_input}"', html)
        self.assertIn(f'hx-post="/{VIEW_ID}/config/"', html)
        self.assertIn(f'hx-target="#{VIEW_ID}-views-bar"', html)

    def test_deleting_a_saved_view_swaps_the_bar(self):
        html = self.render()

        self.assertIn(f'hx-delete="/{VIEW_ID}/config/7/"', html)
        self.assertEqual(html.count(f'hx-target="#{VIEW_ID}-views-bar"'), 3)
