"""The audit log User filter searches username, e-mail and name, never the password hash."""

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from django_smartbase_admin.audit.sb_admin import AdminAuditLogAdmin, _user_search_query


def _where(qs):
    return str(qs.query).split(" WHERE ", 1)[1]


class UserSearchQueryTests(SimpleTestCase):
    def test_searches_username_email_and_name_only(self):
        where = _where(
            _user_search_query(None, User.objects.all(), User, "pbkdf2", "en")
        )
        for field in ("username", "email", "first_name", "last_name"):
            self.assertIn(f'"{field}"', where)
        self.assertNotIn("password", where)

    def test_no_term_leaves_the_queryset_alone(self):
        qs = User.objects.all()
        self.assertIs(_user_search_query(None, qs, User, "", "en"), qs)

    def test_audit_user_filter_uses_it(self):
        user_field = next(
            field
            for field in AdminAuditLogAdmin.sbadmin_list_display
            if getattr(field, "name", None) == "user_display"
        )
        self.assertIs(user_field.filter_widget.search_query_lambda, _user_search_query)


class UserSearchResultTests(TestCase):
    def test_a_hash_fragment_matches_nobody(self):
        user = User.objects.create_user("alice", "alice@example.com", "secret")
        fragment = user.password.split("$")[-1][:6]
        self.assertFalse(
            _user_search_query(None, User.objects.all(), User, fragment, "en").exists()
        )
        self.assertTrue(
            _user_search_query(None, User.objects.all(), User, "alic", "en").exists()
        )
