"""Integration tests for audit log access control and queryset restrictions.

Tests the permission logic documented in AGENTS.md "Access Control" section:
- Superuser vs non-superuser visibility
- object_history filter bypasses user filtering for non-superusers
- restrict_queryset applied when filtering by content_type or object_history
- Unknown models and exceptions fail closed (entries excluded)

Uses Django's built-in auth.User and Group models so the tests run
standalone with SQLite — no external project or database required.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.contrib.contenttypes.models import ContentType

from django_smartbase_admin.audit.models import AdminAuditLog
from django_smartbase_admin.audit.sb_admin import AdminAuditLogAdmin
from django_smartbase_admin.audit.tests.test_audit_integration import (
    BaseAuditTest,
    NoAdminContext,
    build_admin_request,
    create_test_user,
)


class BasePermissionsTest(BaseAuditTest):
    """Base class for audit permissions tests with pre-created audit entries."""

    def setUp(self):
        super().setUp()

        with NoAdminContext():
            self.superuser = User.objects.create_superuser(
                username="superadmin", email="super@example.com", password="testpass"
            )
            self.user_a = create_test_user(username="user_a", email="a@example.com")
            self.user_b = create_test_user(username="user_b", email="b@example.com")
            self.group1 = Group.objects.create(name="Group 1")
            self.group2 = Group.objects.create(name="Group 2")

        AdminAuditLog.objects.all().delete()

        self.admin = AdminAuditLogAdmin(AdminAuditLog, MagicMock())
        self.admin.field_cache = {}

        self.group_ct = ContentType.objects.get_for_model(Group)
        self.user_ct = ContentType.objects.get_for_model(User)

    def _build_request(self, user, filter_data=None, restrict_fn=None):
        return build_admin_request(
            self.factory,
            user,
            AdminAuditLog,
            filter_data=filter_data,
            restrict_fn=restrict_fn,
        )

    def _create_entry(self, user, content_type, object_id, action_type="update"):
        return AdminAuditLog.objects.create(
            user=user,
            content_type=content_type,
            object_id=str(object_id),
            object_repr=f"Object #{object_id}",
            action_type=action_type,
            changes={"name": {"old": "old", "new": "new"}},
            snapshot_before={"name": "old"},
        )

    def _get_queryset(self, request):
        with patch(
            "django_smartbase_admin.services.thread_local.SBAdminThreadLocalService.get_request",
            return_value=request,
        ):
            return self.admin.get_queryset(request)

    def _get_pks(self, request):
        return set(self._get_queryset(request).values_list("pk", flat=True))


class TestUserVisibility(BasePermissionsTest):
    """Superuser vs non-superuser visibility in the global (unfiltered) view."""

    def setUp(self):
        super().setUp()
        self.entry_by_a = self._create_entry(self.user_a, self.group_ct, self.group1.pk)
        self.entry_by_b = self._create_entry(self.user_b, self.group_ct, self.group2.pk)
        self.entry_by_super = self._create_entry(
            self.superuser, self.user_ct, self.user_a.pk
        )

    def test_superuser_sees_all_entries(self):
        request = self._build_request(self.superuser)
        self.assertEqual(self._get_queryset(request).count(), 3)

    def test_non_superuser_sees_only_own_entries(self):
        request = self._build_request(self.user_a)
        self.assertEqual(self._get_pks(request), {self.entry_by_a.pk})

    def test_object_history_filter_shows_all_users_entries(self):
        """Non-superuser sees ALL users' entries when object_history filter is active."""
        filter_data = {
            "object_history": [
                {"value": f"{self.group_ct.pk}:{self.group1.pk}", "label": "Group 1"}
            ],
        }
        request = self._build_request(self.user_a, filter_data)
        pks = self._get_pks(request)
        self.assertIn(self.entry_by_a.pk, pks)
        self.assertIn(self.entry_by_b.pk, pks)


class TestRestrictedQueryset(BasePermissionsTest):
    """restrict_queryset is applied when filtering by content_type or object_history."""

    def setUp(self):
        super().setUp()
        self.entry_g1 = self._create_entry(
            self.superuser, self.group_ct, self.group1.pk
        )
        self.entry_g2 = self._create_entry(
            self.superuser, self.group_ct, self.group2.pk
        )
        self.entry_user = self._create_entry(
            self.superuser, self.user_ct, self.user_a.pk
        )

    def _restrict_to_group1(self, qs, model, **kwargs):
        if model == Group:
            return qs.filter(pk=self.group1.pk)
        return qs

    def test_content_type_filter_restricts_entries(self):
        """Only entries for objects allowed by restrict_queryset are shown."""
        filter_data = {
            "content_type": [{"value": str(self.group_ct.pk), "label": "auth.group"}],
        }
        request = self._build_request(
            self.superuser, filter_data, self._restrict_to_group1
        )
        pks = self._get_pks(request)

        self.assertIn(self.entry_g1.pk, pks)
        self.assertNotIn(self.entry_g2.pk, pks)
        # Non-filtered content type entries are not restricted
        self.assertIn(self.entry_user.pk, pks)

    def test_object_history_filter_also_restricts(self):
        """restrict_queryset is applied even when filtering by object_history."""
        filter_data = {
            "object_history": [
                {"value": f"{self.group_ct.pk}:{self.group2.pk}", "label": "Group 2"}
            ],
        }

        def restrict_excludes_group2(qs, model, **kwargs):
            if model == Group:
                return qs.exclude(pk=self.group2.pk)
            return qs

        request = self._build_request(
            self.superuser, filter_data, restrict_excludes_group2
        )
        pks = self._get_pks(request)
        self.assertNotIn(self.entry_g2.pk, pks)


class TestFailClosed(BasePermissionsTest):
    """Unknown models and exceptions during restriction fail closed."""

    def setUp(self):
        super().setUp()
        self.entry_group = self._create_entry(
            self.superuser, self.group_ct, self.group1.pk
        )
        self.entry_user = self._create_entry(
            self.superuser, self.user_ct, self.user_a.pk
        )

    def test_unknown_model_entries_excluded(self):
        """Content type with no model_class() → entries excluded, others unaffected."""
        fake_ct = ContentType.objects.create(app_label="nonexistent", model="gone")
        fake_entry = self._create_entry(self.superuser, fake_ct, 999)

        filter_data = {
            "content_type": [{"value": str(fake_ct.pk), "label": "nonexistent.gone"}],
        }
        request = self._build_request(self.superuser, filter_data)
        pks = self._get_pks(request)

        self.assertNotIn(fake_entry.pk, pks)
        self.assertIn(self.entry_group.pk, pks)

    def test_exception_during_restriction_excludes_entries(self):
        """If restrict_queryset raises, entries for that content type are excluded."""

        def exploding_restrict(qs, model, **kwargs):
            if model == Group:
                raise RuntimeError("boom")
            return qs

        filter_data = {
            "content_type": [{"value": str(self.group_ct.pk), "label": "auth.group"}],
        }
        request = self._build_request(self.superuser, filter_data, exploding_restrict)
        pks = self._get_pks(request)

        self.assertNotIn(self.entry_group.pk, pks)
        self.assertIn(self.entry_user.pk, pks)

    def test_mixed_success_and_failure(self):
        """Successful restriction shown, failed restriction excluded."""

        def restrict_fails_for_users(qs, model, **kwargs):
            if model == User:
                raise RuntimeError("fail")
            return qs

        filter_data = {
            "content_type": [
                {"value": str(self.group_ct.pk), "label": "auth.group"},
                {"value": str(self.user_ct.pk), "label": "auth.user"},
            ],
        }
        request = self._build_request(
            self.superuser, filter_data, restrict_fails_for_users
        )
        pks = self._get_pks(request)

        self.assertIn(self.entry_group.pk, pks)
        self.assertNotIn(self.entry_user.pk, pks)


class TestListHistoryButton(BasePermissionsTest):
    """History button on list views."""

    def test_audit_log_admin_has_history_disabled(self):
        self.assertFalse(self.admin.sbadmin_list_history_enabled)

    def test_list_history_enabled_by_default(self):
        from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView

        self.assertTrue(SBAdminBaseListView.sbadmin_list_history_enabled)

    def test_history_action_has_no_params_true(self):
        """History action must set no_params=True to prevent JS appending duplicate ?params=."""
        from django_smartbase_admin.engine.admin_base_view import SBAdminBaseListView

        class FakeListView(SBAdminBaseListView):
            model = Group
            sbadmin_list_history_enabled = True
            sbadmin_list_reorder_field = None

            def get_sbadmin_list_actions(self, request):
                return []

        fake_view = FakeListView.__new__(FakeListView)
        with patch(
            "django_smartbase_admin.audit.views.reverse",
            return_value="/sb-admin/audit/adminauditlog/",
        ):
            actions = fake_view._get_sbadmin_list_actions(MagicMock())

        history_actions = [a for a in actions if str(a.title) == "History"]
        self.assertEqual(len(history_actions), 1, "Expected exactly one History action")
        self.assertTrue(
            history_actions[0].no_params, "History action must use no_params=True"
        )
        self.assertIn(
            "?", history_actions[0].url, "History URL must include query params"
        )
