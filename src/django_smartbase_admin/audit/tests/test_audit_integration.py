"""Integration tests for audit logging via admin operations.

Uses Django's built-in auth.User and Group models so the tests run
standalone with SQLite — no external project or database required.
"""

from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TransactionTestCase

from django_smartbase_admin.audit.manager import (
    install_manager_hooks,
    uninstall_manager_hooks,
)
from django_smartbase_admin.audit.models import AdminAuditLog
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.views import SBAdminViewService


def create_test_user(username="testuser", email="test@example.com"):
    return User.objects.create_user(username=username, email=email, password="testpass")


def make_mock_configuration(restrict_fn=None):
    """Create a mock SBAdmin configuration.

    Args:
        restrict_fn: Optional callable(qs, model, request, request_data, **kw) -> qs.
            Defaults to identity (no restriction).
    """
    config = MagicMock()
    config.restrict_queryset = restrict_fn or (lambda qs, **kwargs: qs)
    config.apply_global_filter_to_queryset = lambda qs, *a, **kw: qs
    return config


def build_admin_request(factory, user, model, filter_data=None, restrict_fn=None):
    """Build a request with SBAdmin-style filter params and configuration.

    Uses ``SBAdminViewService`` to construct the query string exactly as
    production code does.

    Args:
        factory: Django RequestFactory instance.
        user: User instance for request.user.
        model: The Django model class whose admin list view is being simulated.
        filter_data: Dict of filter key/value pairs (e.g. {"content_type": [...]}).
        restrict_fn: Optional restrict_queryset callable for the configuration.
    """
    view_id = SBAdminViewService.get_model_path(model)
    filter_data = filter_data or {}
    if filter_data:
        query_string = SBAdminViewService.build_list_params_url(view_id, filter_data)
    else:
        query_string = SBAdminViewService.build_list_url(view_id, {})

    request = factory.get(f"/admin/?{query_string}")
    request.user = user

    request_data = SBAdminViewRequestData(
        view=view_id,
        action=None,
        modifier=None,
        user=user,
        request_get=request.GET,
        request_method="GET",
    )
    request_data.additional_data = {}
    request_data.configuration = make_mock_configuration(restrict_fn)
    request.request_data = request_data
    return request


class MockSBAdminContext:
    """Context manager to simulate SBAdmin request context."""

    def __init__(self, user=None, parent_model=None, parent_object_id=None):
        self.mock_request = MagicMock()
        if user is not None:
            self.mock_request.user = user
        else:
            self.mock_request.user = MagicMock(is_authenticated=True)
        self.mock_request._audit_request_id = None

        if parent_model and parent_object_id:
            self.mock_request.request_data = MagicMock()
            self.mock_request.request_data.object_id = parent_object_id
            self.mock_request.request_data.selected_view = MagicMock()
            self.mock_request.request_data.selected_view.model = parent_model
        else:
            self.mock_request.request_data = MagicMock()
            self.mock_request.request_data.object_id = None

        self._patcher = None

    def __enter__(self):
        self._patcher = patch(
            "django_smartbase_admin.services.thread_local.SBAdminThreadLocalService.get_request",
            return_value=self.mock_request,
        )
        self._patcher.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._patcher:
            self._patcher.stop()


class NoAdminContext:
    """Context manager to ensure no SBAdmin context."""

    def __init__(self):
        self._patcher = None

    def __enter__(self):
        self._patcher = patch(
            "django_smartbase_admin.services.thread_local.SBAdminThreadLocalService.get_request",
            return_value=None,
        )
        self._patcher.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._patcher:
            self._patcher.stop()


class MockModelAdmin:
    """Simulates Django ModelAdmin behavior for testing."""

    def __init__(self, model, admin_site=None):
        self.model = model
        self.admin_site = admin_site or AdminSite()

    def save_model(self, request, obj, form, change):
        obj.save()

    def delete_model(self, request, obj):
        obj.delete()

    def delete_queryset(self, request, queryset):
        queryset.delete()

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            instance.save()
        formset.save_m2m()


class MockFormset:
    """Mock formset for testing inline operations."""

    def __init__(self, instances=None, deleted_objects=None):
        self._instances = instances or []
        self.deleted_objects = deleted_objects or []

    def save(self, commit=True):
        return self._instances

    def save_m2m(self):
        pass


class BaseAuditTest(TransactionTestCase):
    """Base class that installs/uninstalls manager hooks."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        install_manager_hooks()

    @classmethod
    def tearDownClass(cls):
        uninstall_manager_hooks()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        AdminAuditLog.objects.all().delete()
        with NoAdminContext():
            self.admin_user = create_test_user()
        self.factory = RequestFactory()


class TestAdminCRUD(BaseAuditTest):
    """Test audit logging for Create, Update, Delete operations."""

    def setUp(self):
        super().setUp()
        self.admin = MockModelAdmin(Group)
        self.request = self.factory.post("/admin/")
        self.request.user = self.admin_user
        self.group_ct = ContentType.objects.get_for_model(Group)

    def test_create_logs_new_values(self):
        group = Group(name="Test Group")
        with MockSBAdminContext(user=self.admin_user):
            self.admin.save_model(self.request, group, form=None, change=False)

        log = AdminAuditLog.objects.get(
            content_type=self.group_ct, action_type="create"
        )
        self.assertEqual(log.object_id, str(group.pk))
        self.assertEqual(log.object_repr, "Test Group")
        self.assertEqual(log.changes["name"]["old"], None)
        self.assertEqual(log.changes["name"]["new"], "Test Group")
        self.assertEqual(log.snapshot_before, {})
        self.assertIsNotNone(log.request_id)

    def test_update_logs_old_and_new_values(self):
        with NoAdminContext():
            group = Group.objects.create(name="Original")
        AdminAuditLog.objects.all().delete()

        group.name = "Updated"
        with MockSBAdminContext(user=self.admin_user):
            self.admin.save_model(self.request, group, form=None, change=True)

        log = AdminAuditLog.objects.get(
            content_type=self.group_ct, action_type="update"
        )
        self.assertEqual(log.changes["name"]["old"], "Original")
        self.assertEqual(log.changes["name"]["new"], "Updated")
        self.assertEqual(log.snapshot_before["name"], "Original")

    def test_delete_logs_snapshot_before(self):
        with NoAdminContext():
            group = Group.objects.create(name="To Delete")
        group_pk = group.pk
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            self.admin.delete_model(self.request, group)

        log = AdminAuditLog.objects.get(
            content_type=self.group_ct, action_type="delete"
        )
        self.assertEqual(log.object_id, str(group_pk))
        self.assertEqual(log.snapshot_before["name"], "To Delete")
        self.assertEqual(log.changes, {})

    def test_bulk_delete_records_count_and_items(self):
        with NoAdminContext():
            g1 = Group.objects.create(name="Bulk 1")
            g2 = Group.objects.create(name="Bulk 2")
            g3 = Group.objects.create(name="Bulk 3")
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            self.admin.delete_queryset(
                self.request, Group.objects.filter(name__startswith="Bulk")
            )

        log = AdminAuditLog.objects.get(action_type="bulk_delete")
        self.assertTrue(log.is_bulk)
        self.assertEqual(log.bulk_count, 3)
        deleted_ids = {item["id"] for item in log.changes["deleted"]}
        self.assertEqual(deleted_ids, {g1.pk, g2.pk, g3.pk})


class TestBulkUpdate(BaseAuditTest):
    """Test audit logging for QuerySet.update() operations."""

    def setUp(self):
        super().setUp()
        with NoAdminContext():
            self.u1 = create_test_user(username="bulk1", email="bulk1@example.com")
            self.u2 = create_test_user(username="bulk2", email="bulk2@example.com")
            self.u3 = create_test_user(username="bulk3", email="bulk3@example.com")
            User.objects.filter(pk=self.u3.pk).update(is_staff=True)
        AdminAuditLog.objects.all().delete()

    def test_bulk_update_groups_by_old_value(self):
        with MockSBAdminContext(user=self.admin_user):
            User.objects.filter(username__startswith="bulk").update(
                is_staff=True, is_active=False
            )

        log = AdminAuditLog.objects.get(action_type="bulk_update")
        self.assertTrue(log.is_bulk)
        self.assertEqual(log.bulk_count, 3)

        by_old_staff = log.changes["is_staff"]["by_old"]
        self.assertEqual(len(by_old_staff["False"]), 2)
        self.assertEqual(len(by_old_staff["True"]), 1)

    def test_single_item_update_records_old_and_new(self):
        with MockSBAdminContext(user=self.admin_user):
            User.objects.filter(pk=self.u1.pk).update(is_staff=True)

        log = AdminAuditLog.objects.get(object_id=str(self.u1.pk))
        self.assertEqual(log.action_type, "update")
        self.assertFalse(log.is_bulk)
        self.assertEqual(log.changes["is_staff"]["old"], False)
        self.assertEqual(log.changes["is_staff"]["new"], True)


class TestInlineFormset(BaseAuditTest):
    """Test audit logging for inline formset operations with parent context."""

    def setUp(self):
        super().setUp()
        self.admin = MockModelAdmin(Group)
        self.request = self.factory.post("/admin/")
        self.request.user = self.admin_user
        self.user_ct = ContentType.objects.get_for_model(User)
        self.parent_id = str(self.admin_user.pk)

    def _save_formset(self, formset):
        with MockSBAdminContext(
            user=self.admin_user,
            parent_model=User,
            parent_object_id=self.parent_id,
        ):
            self.admin.save_formset(
                self.request, form=None, formset=formset, change=True
            )

    def test_inline_create_records_parent_context(self):
        self._save_formset(
            MockFormset(instances=[Group(name="Inline 1"), Group(name="Inline 2")])
        )

        logs = list(AdminAuditLog.objects.filter(action_type="create"))
        self.assertEqual(len(logs), 2)
        for log in logs:
            self.assertEqual(log.parent_content_type, self.user_ct)
            self.assertEqual(log.parent_object_id, self.parent_id)
        self.assertEqual(
            {log.changes["name"]["new"] for log in logs}, {"Inline 1", "Inline 2"}
        )

    def test_inline_update_records_diff_and_parent(self):
        with NoAdminContext():
            group = Group.objects.create(name="Before")
        AdminAuditLog.objects.all().delete()

        group.name = "After"
        self._save_formset(MockFormset(instances=[group]))

        log = AdminAuditLog.objects.get(action_type="update")
        self.assertEqual(log.changes["name"]["old"], "Before")
        self.assertEqual(log.changes["name"]["new"], "After")
        self.assertEqual(log.parent_content_type, self.user_ct)

    def test_inline_delete_records_snapshot_and_parent(self):
        with NoAdminContext():
            group = Group.objects.create(name="To Delete")
        group_pk = group.pk
        AdminAuditLog.objects.all().delete()

        self._save_formset(MockFormset(deleted_objects=[group]))

        log = AdminAuditLog.objects.get(action_type="delete")
        self.assertEqual(log.object_id, str(group_pk))
        self.assertEqual(log.snapshot_before["name"], "To Delete")
        self.assertEqual(log.parent_content_type, self.user_ct)


class TestRequestIdGrouping(BaseAuditTest):
    """Test that operations in same/different requests get correct request_ids."""

    def test_same_request_shares_request_id(self):
        admin = MockModelAdmin(Group)
        request = self.factory.post("/admin/")
        request.user = self.admin_user

        with NoAdminContext():
            group_to_delete = Group.objects.create(name="To Delete")
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            admin.save_model(request, Group(name="Created"), form=None, change=False)
            admin.delete_model(request, group_to_delete)

        logs = list(AdminAuditLog.objects.all())
        self.assertEqual(len(logs), 2)
        request_ids = {log.request_id for log in logs}
        self.assertEqual(len(request_ids), 1)
        self.assertIsNotNone(list(request_ids)[0])

    def test_different_requests_get_different_ids(self):
        admin = MockModelAdmin(Group)
        request = self.factory.post("/admin/")
        request.user = self.admin_user

        with MockSBAdminContext(user=self.admin_user):
            admin.save_model(request, Group(name="Request 1"), form=None, change=False)

        with MockSBAdminContext(user=self.admin_user):
            admin.save_model(request, Group(name="Request 2"), form=None, change=False)

        logs = list(AdminAuditLog.objects.all())
        self.assertEqual(len(logs), 2)
        self.assertNotEqual(logs[0].request_id, logs[1].request_id)


class TestSkipBehavior(BaseAuditTest):
    """Test skip fields, skip models, and no-context behavior."""

    def test_last_login_only_change_not_logged(self):
        from django.utils import timezone

        with MockSBAdminContext(user=self.admin_user):
            User.objects.filter(pk=self.admin_user.pk).update(last_login=timezone.now())

        self.assertEqual(
            AdminAuditLog.objects.filter(
                content_type=ContentType.objects.get_for_model(User),
                object_id=str(self.admin_user.pk),
            ).count(),
            0,
        )

    def test_session_model_not_audited(self):
        from django.contrib.sessions.models import Session
        from django.utils import timezone

        with MockSBAdminContext(user=self.admin_user):
            Session.objects.create(
                session_key="test" + "x" * 36,
                session_data="data",
                expire_date=timezone.now() + timezone.timedelta(days=1),
            )

        self.assertEqual(
            AdminAuditLog.objects.filter(
                content_type=ContentType.objects.get_for_model(Session)
            ).count(),
            0,
        )

    def test_no_admin_context_not_logged(self):
        with NoAdminContext():
            group = Group.objects.create(name="No Context")
            group.name = "Updated"
            group.save()
            group.delete()

        self.assertEqual(AdminAuditLog.objects.count(), 0)


class TestHistoryTraversal(BaseAuditTest):
    """Test querying audit logs for sequential changes."""

    def test_sequential_updates_form_old_new_chain(self):
        admin = MockModelAdmin(Group)
        request = self.factory.post("/admin/")
        request.user = self.admin_user
        group_ct = ContentType.objects.get_for_model(Group)

        with NoAdminContext():
            target = Group.objects.create(name="Original")
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            target.name = "First Change"
            admin.save_model(request, target, form=None, change=True)

        with MockSBAdminContext(user=self.admin_user):
            target.name = "Second Change"
            admin.save_model(request, target, form=None, change=True)

        logs = list(
            AdminAuditLog.objects.filter(
                content_type=group_ct, object_id=str(target.pk)
            ).order_by("timestamp")
        )
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].changes["name"]["old"], "Original")
        self.assertEqual(logs[0].changes["name"]["new"], "First Change")
        self.assertEqual(logs[1].changes["name"]["old"], "First Change")
        self.assertEqual(logs[1].changes["name"]["new"], "Second Change")


class TestFKAffectedObjects(BaseAuditTest):
    """Test that FK changes record affected objects."""

    def test_fk_change_records_old_and_new_targets(self):
        with NoAdminContext():
            ct_user = ContentType.objects.get_for_model(User)
            ct_group = ContentType.objects.get_for_model(Group)
            perm = Permission.objects.create(
                codename="test_fk", name="Test FK", content_type=ct_user
            )
        AdminAuditLog.objects.all().delete()

        admin = MockModelAdmin(Permission)
        request = self.factory.post("/admin/")
        request.user = self.admin_user

        perm.content_type = ct_group
        with MockSBAdminContext(user=self.admin_user):
            admin.save_model(request, perm, form=None, change=True)

        log = AdminAuditLog.objects.get(action_type="update")
        self.assertEqual(log.changes["content_type"]["old"], ct_user.pk)
        self.assertEqual(log.changes["content_type"]["new"], ct_group.pk)

        if log.affected_objects:
            affected_ids = {item["id"] for item in log.affected_objects}
            self.assertIn(ct_user.pk, affected_ids)
            self.assertIn(ct_group.pk, affected_ids)


class TestM2MChanges(BaseAuditTest):
    """Test audit logging for M2M changes via through model."""

    def setUp(self):
        super().setUp()
        with NoAdminContext():
            self.group1 = Group.objects.create(name="Group 1")
            self.group2 = Group.objects.create(name="Group 2")
            self.group3 = Group.objects.create(name="Group 3")
        AdminAuditLog.objects.all().delete()
        self.through_model_name = User.groups.through._meta.model_name

    def _get_through_logs(self, **extra_filters):
        return AdminAuditLog.objects.filter(
            content_type__model=self.through_model_name,
            **extra_filters,
        )

    def test_m2m_add_logs_through_model(self):
        with MockSBAdminContext(user=self.admin_user):
            self.admin_user.groups.add(self.group1, self.group2)

        logs = self._get_through_logs()
        self.assertGreaterEqual(logs.count(), 1)
        self.assertIn(logs.first().action_type, ["create", "bulk_create"])

    def test_m2m_remove_logs_delete(self):
        with NoAdminContext():
            self.admin_user.groups.add(self.group1, self.group2)
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            self.admin_user.groups.remove(self.group1)

        log = self._get_through_logs(action_type__in=["delete", "bulk_delete"]).get()
        self.assertTrue(log.snapshot_before)

    def test_m2m_clear_logs_bulk_delete(self):
        with NoAdminContext():
            self.admin_user.groups.add(self.group1, self.group2, self.group3)
        AdminAuditLog.objects.all().delete()

        with MockSBAdminContext(user=self.admin_user):
            self.admin_user.groups.clear()

        log = self._get_through_logs(action_type__in=["delete", "bulk_delete"]).get()
        if log.action_type == "bulk_delete":
            self.assertEqual(log.bulk_count, 3)

    def test_m2m_operations_share_request_id(self):
        with MockSBAdminContext(user=self.admin_user):
            self.admin_user.groups.add(self.group1)
            self.admin_user.groups.add(self.group2)

        logs = AdminAuditLog.objects.all()
        self.assertGreaterEqual(logs.count(), 2)
        request_ids = set(logs.values_list("request_id", flat=True))
        self.assertEqual(len(request_ids), 1)
