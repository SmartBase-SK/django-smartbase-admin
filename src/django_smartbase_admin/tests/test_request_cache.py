from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from django_smartbase_admin.services.configuration import (
    SBAdminUserConfigurationService,
)
from django_smartbase_admin.services.request_cache import cache_on_request


class RequestCacheTest(SimpleTestCase):
    def test_cache_on_request_uses_single_request_cache_dict(self):
        request = RequestFactory().get("/")
        calls = 0

        def load():
            nonlocal calls
            calls += 1
            return {"value": calls}

        first = cache_on_request("sample:key", load, request=request)
        second = cache_on_request("sample:key", load, request=request)

        self.assertIs(first, second)
        self.assertEqual(calls, 1)
        self.assertEqual(list(request._sbadmin_request_cache), ["sample:key"])

    def test_cache_on_request_caches_none_value(self):
        request = RequestFactory().get("/")
        calls = 0

        def load():
            nonlocal calls
            calls += 1
            return None

        self.assertIsNone(cache_on_request("sample:none", load, request=request))
        self.assertIsNone(cache_on_request("sample:none", load, request=request))
        self.assertEqual(calls, 1)

    def test_cache_on_request_without_request_does_not_cache(self):
        calls = 0

        def load():
            nonlocal calls
            calls += 1
            return calls

        self.assertEqual(cache_on_request("sample:no-request", load), 1)
        self.assertEqual(cache_on_request("sample:no-request", load), 2)


class UserConfigRequestCacheTest(SimpleTestCase):
    def test_get_user_config_is_cached_per_request(self):
        request = RequestFactory().get("/")
        calls = 0

        class Configuration:
            @staticmethod
            def get_user_config(request):
                nonlocal calls
                calls += 1
                return SimpleNamespace(call_number=calls)

        with patch(
            "django_smartbase_admin.services.configuration.import_string",
            return_value=Configuration,
        ):
            first = SBAdminUserConfigurationService.get_user_config(request)
            second = SBAdminUserConfigurationService.get_user_config(request)

        self.assertIs(first, second)
        self.assertEqual(first.call_number, 1)
        self.assertEqual(calls, 1)

    def test_get_user_config_cache_is_request_scoped(self):
        first_request = RequestFactory().get("/")
        second_request = RequestFactory().get("/")
        calls = 0

        class Configuration:
            @staticmethod
            def get_user_config(request):
                nonlocal calls
                calls += 1
                return SimpleNamespace(call_number=calls)

        with patch(
            "django_smartbase_admin.services.configuration.import_string",
            return_value=Configuration,
        ):
            first = SBAdminUserConfigurationService.get_user_config(first_request)
            second = SBAdminUserConfigurationService.get_user_config(second_request)

        self.assertIsNot(first, second)
        self.assertEqual(first.call_number, 1)
        self.assertEqual(second.call_number, 2)
