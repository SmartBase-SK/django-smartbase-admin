import json

from django.test import SimpleTestCase

from django_smartbase_admin.services.url_params_codec import (
    dumps_for_url,
    loads_from_url,
)


class UrlParamsCodecTests(SimpleTestCase):
    def test_roundtrip_compressed(self):
        payload = {
            "blog_article": {
                "filterData": {"status": "published"},
                "columnsData": {"columns": {"title": {"visible": True}}},
            }
        }
        encoded = dumps_for_url(payload)
        self.assertFalse(encoded.lstrip().startswith("{"))
        self.assertEqual(loads_from_url(encoded), payload)

    def test_plain_json(self):
        payload = {"blog_article": {"filterData": {"status": "draft"}}}
        legacy = json.dumps(payload, separators=(",", ":"))
        self.assertEqual(loads_from_url(legacy), payload)

    def test_empty_and_invalid(self):
        self.assertEqual(loads_from_url(""), {})
        self.assertEqual(loads_from_url(None), {})
        self.assertEqual(loads_from_url("not-valid"), {})
        self.assertEqual(loads_from_url("w"), {})
