"""Regression tests for modal media serialization in SBAdmin change form."""

import json
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from js_asset import JS

from ckeditor.widgets import CKEditorWidget

from django_smartbase_admin.admin.admin_base import SBAdmin


class ModalMediaSerializationTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.admin = SBAdmin.__new__(SBAdmin)

    @patch("django.contrib.admin.options.ModelAdmin.render_change_form")
    def test_modal_ckeditor_widget_media_is_json_serializable(
        self, mock_render_change_form
    ):
        media = CKEditorWidget().media
        context = {"sbadmin_is_modal": True, "media": media}
        self.admin.render_change_form(self.request, context)
        json.dumps(context["media_json"])
