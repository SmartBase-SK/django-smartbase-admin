import json

from django.test import SimpleTestCase

from django_smartbase_admin.services.url_params_codec import (
    dumps_for_url,
    extract_params_from_changelist_filters,
    loads_from_url,
    parse_changelist_filters,
)


class UrlParamsCodecTests(SimpleTestCase):
    def test_roundtrip_compressed(self):
        payload = {
            "blog_article": {
                "filterData": {"status": "published"},
                "columnsData": {"columns": {"title": {"visible": True}}},
            }
        }
        encoded = dumps_for_url(payload, compress=True)
        self.assertFalse(encoded.lstrip().startswith("{"))
        self.assertEqual(loads_from_url(encoded), payload)

    def test_plain_json_encode(self):
        payload = {"blog_article": {"filterData": {"status": "draft"}}}
        encoded = dumps_for_url(payload, compress=False)
        self.assertTrue(encoded.lstrip().startswith("{"))
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

    def test_changelist_filters_preserves_plus(self):
        token = "N4Igz+compressed+token"
        raw_filters = f"params={token}"
        self.assertEqual(extract_params_from_changelist_filters(raw_filters), token)
        self.assertEqual(parse_changelist_filters(""), {})
