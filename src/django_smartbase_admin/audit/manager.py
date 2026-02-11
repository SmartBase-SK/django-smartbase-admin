"""
QuerySet hooks for comprehensive audit logging.
Patches Django's QuerySet methods to intercept database operations.
"""

import logging
import uuid
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from django_smartbase_admin.audit.utils.serialization import serialize_instance
from django_smartbase_admin.audit.utils.diff import (
    compute_diff,
    compute_bulk_diff,
    compute_bulk_snapshot,
)

logger = logging.getLogger(__name__)

# Models to skip auditing (besides AdminAuditLog)
SKIP_MODELS = {
    ("admin", "logentry"),  # Django's built-in admin log
    ("sessions", "session"),  # Session data
    ("contenttypes", "contenttype"),  # Content types
}

# Field names to skip per model: {("app_label", "model_name"): {"field1", "field2"}}
SKIP_FIELDS = {
    ("auth", "user"): {"last_login"},
}

_original_qs_update = None
_original_qs_delete = None
_original_qs_bulk_create = None
_original_qs_bulk_update = None
_original_model_save = None
_original_model_delete = None
_hooks_installed = False


def _is_in_admin_context() -> bool:
    """Check if we're in an SBAdmin request context."""
    try:
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        request = SBAdminThreadLocalService.get_request()
        return request is not None
    except Exception:
        return False


def _should_audit_model(model) -> bool:
    """Check if this model should be audited. Only audits in SBAdmin context."""
    if model is None:
        return False

    # Only audit in SBAdmin request context
    if not _is_in_admin_context():
        return False

    # Never audit the audit log itself to prevent infinite recursion
    from django_smartbase_admin.audit.models import AdminAuditLog

    if model == AdminAuditLog:
        return False

    # Skip models in the skip list
    model_key = (model._meta.app_label, model._meta.model_name)
    if model_key in SKIP_MODELS:
        return False
    from django.conf import settings

    if model_key in getattr(settings, "SB_ADMIN_AUDIT_SKIP_MODELS", ()):
        return False

    return True


def _get_skip_fields(model) -> set[str]:
    """Get field names that should be skipped (auto_now, auto_now_add, and per-model config)."""
    from django.conf import settings

    skip_fields = set()
    model_key = (model._meta.app_label, model._meta.model_name)

    # Add per-model skip fields from defaults and settings
    if model_key in SKIP_FIELDS:
        skip_fields.update(SKIP_FIELDS[model_key])
    extra = getattr(settings, "SB_ADMIN_AUDIT_SKIP_FIELDS", {})
    if model_key in extra:
        skip_fields.update(extra[model_key])

    # Add auto_now and auto_now_add fields
    for field in model._meta.get_fields():
        if hasattr(field, "auto_now") and field.auto_now:
            skip_fields.add(field.name)
        if hasattr(field, "auto_now_add") and field.auto_now_add:
            skip_fields.add(field.name)

    return skip_fields


def _filter_skip_fields(model, data: dict) -> dict:
    """Remove skipped fields (auto_now, auto_now_add, SKIP_FIELDS) from a dict."""
    skip_fields = _get_skip_fields(model)
    return {k: v for k, v in data.items() if k not in skip_fields}


def _extract_fk_affected(model, changes: dict) -> list[dict]:
    """
    Extract affected FK objects from changes.
    Returns list of {"ct": "app.model", "id": pk, "repr": "..."} for all FK changes.
    """
    from django.db.models import ForeignKey

    affected = []

    for field_name, change in changes.items():
        try:
            field = model._meta.get_field(field_name)
        except Exception:
            continue

        if not isinstance(field, ForeignKey):
            continue

        related_model = field.related_model
        ct_label = f"{related_model._meta.app_label}.{related_model._meta.model_name}"

        # Get old and new values
        if isinstance(change, dict):
            old_val = change.get("old")
            new_val = change.get("new")
            old_repr = change.get("old_display")
            new_repr = change.get("new_display")
        else:
            old_val = None
            new_val = change
            old_repr = None
            new_repr = None

        # Add old value if present
        if old_val:
            obj_repr = old_repr or _get_object_repr(related_model, old_val)
            affected.append({"ct": ct_label, "id": int(old_val), "repr": obj_repr})

        # Add new value if present and different
        if new_val and new_val != old_val:
            obj_repr = new_repr or _get_object_repr(related_model, new_val)
            affected.append({"ct": ct_label, "id": int(new_val), "repr": obj_repr})

    return affected


def _get_object_repr(model, pk) -> str:
    """Try to get object repr, fallback to ID."""
    try:
        obj = model._default_manager.get(pk=pk)
        return str(obj)
    except Exception:
        return f"#{pk}"


def _get_request_id() -> uuid.UUID | None:
    """
    Get or create a request_id to group changes from the same request.

    Stores the request_id directly on the request object, so it's automatically
    scoped to the request lifecycle and cleaned up when the request ends.
    """
    try:
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        request = SBAdminThreadLocalService.get_request()
        if request is None:
            return None

        # Store/retrieve request_id directly on the request object
        if not hasattr(request, "_audit_request_id"):
            request._audit_request_id = uuid.uuid4()
        return request._audit_request_id
    except Exception:
        return None


def _get_parent_context() -> tuple[type | None, str, str]:
    """
    Get parent context from SBAdmin request_data.
    Returns (parent_model, parent_object_id, parent_object_repr) or (None, "", "").
    """
    try:
        from django_smartbase_admin.services.thread_local import (
            SBAdminThreadLocalService,
        )

        request = SBAdminThreadLocalService.get_request()
        if request is None:
            return None, "", ""

        request_data = getattr(request, "request_data", None)
        if request_data is None:
            return None, "", ""

        # Get the view being edited (e.g., "user_config_queuebundle")
        selected_view = getattr(request_data, "selected_view", None)
        if selected_view is None:
            return None, "", ""

        # Get the model from the view
        parent_model = getattr(selected_view, "model", None)
        if parent_model is None:
            return None, "", ""

        # Get the object_id being edited
        object_id = getattr(request_data, "object_id", None)
        if not object_id:
            return None, "", ""

        # Try to get the object repr
        try:
            parent_obj = parent_model._default_manager.get(pk=object_id)
            parent_repr = str(parent_obj)[:255]
        except Exception:
            parent_repr = f"{parent_model.__name__} #{object_id}"

        return parent_model, str(object_id), parent_repr

    except Exception:
        return None, "", ""


def _create_audit_log(
    action_type: str,
    model,
    object_id: str = "",
    object_repr: str = "",
    snapshot_before: dict | None = None,
    changes: dict | None = None,
    is_bulk: bool = False,
    bulk_count: int = 0,
    affected_objects: list | None = None,
):
    """Create an audit log entry. Uses transaction.atomic() to not break main transaction."""
    from django_smartbase_admin.audit.models import AdminAuditLog

    # Wrap everything in transaction.atomic() so any DB error (ContentType lookup,
    # _extract_fk_affected, _get_parent_context, or the INSERT itself)
    # is isolated and does not poison the outer transaction.
    # NOTE: bare connection.savepoint_rollback() does NOT clear needs_rollback,
    # but transaction.atomic().__exit__ does — this is critical for correctness.
    try:
        with transaction.atomic():
            # Get user from request (same source as _get_request_id)
            user = None
            try:
                from django_smartbase_admin.services.thread_local import (
                    SBAdminThreadLocalService,
                )

                request = SBAdminThreadLocalService.get_request()
                if (
                    request
                    and hasattr(request, "user")
                    and request.user.is_authenticated
                ):
                    user = request.user
            except Exception:
                pass

            content_type = ContentType.objects.get_for_model(model)

            audit_kwargs = {
                "user": user,
                "request_id": _get_request_id(),
                "content_type": content_type,
                "object_id": str(object_id) if object_id else "",
                "object_repr": object_repr[:255] if object_repr else "",
                "action_type": action_type,
                "snapshot_before": snapshot_before or {},
                "changes": changes or {},
                "is_bulk": is_bulk,
                "bulk_count": bulk_count,
            }

            # Use explicitly passed affected objects, or auto-detect from FK changes
            if affected_objects:
                audit_kwargs["affected_objects"] = affected_objects
            elif changes:
                # Auto-detect affected FK objects from changes
                affected = _extract_fk_affected(model, changes)
                if affected:
                    audit_kwargs["affected_objects"] = affected

            # Auto-detect parent context from SBAdmin request_data
            parent_model, parent_id, parent_repr = _get_parent_context()
            if (
                parent_model and parent_model != model
            ):  # Don't set parent if editing the model itself
                audit_kwargs["parent_content_type"] = ContentType.objects.get_for_model(
                    parent_model
                )
                audit_kwargs["parent_object_id"] = parent_id
                audit_kwargs["parent_object_repr"] = parent_repr

            AdminAuditLog.objects.create(**audit_kwargs)

    except Exception:
        logger.exception(
            "Audit: Failed to create audit log for %s %s", action_type, model.__name__
        )


def audited_qs_update(self, **kwargs):
    """Audited version of QuerySet.update()."""
    model = self.model

    if not _should_audit_model(model):
        return _original_qs_update(self, **kwargs)

    # Capture objects before update — in atomic block so failures don't poison the transaction
    pks = []
    objects_before = []
    displays_before = []
    try:
        with transaction.atomic():
            pks = list(self.values_list("pk", flat=True))
            if len(pks) == 1:
                objs = list(self.model._default_manager.filter(pk__in=pks))
                for obj in objs:
                    data, display = serialize_instance(obj, include_display=True)
                    objects_before.append(data)
                    displays_before.append(display)
            else:
                objects_before = [
                    serialize_instance(obj)
                    for obj in self.model._default_manager.filter(pk__in=pks)
                ]
    except Exception:
        logger.debug(
            "Audit: Could not capture objects before qs.update() for %s",
            model.__name__,
            exc_info=True,
        )
        pks = []
        objects_before = []
        displays_before = []

    # Perform the update
    result = _original_qs_update(self, **kwargs)

    if not pks:
        return result

    # Post-update audit
    try:
        if len(pks) == 1:
            pk = pks[0]
            before = objects_before[0] if objects_before else {}
            display_before = displays_before[0] if displays_before else {}

            # Capture "after" state — in atomic block so a DB failure doesn't poison the transaction
            obj = None
            after = {}
            display_after = {}
            try:
                with transaction.atomic():
                    obj = model._default_manager.get(pk=pk)
                    after, display_after = serialize_instance(obj, include_display=True)
            except model.DoesNotExist:
                pass
            except Exception:
                logger.debug(
                    "Audit: Could not capture after state for qs.update() %s",
                    model.__name__,
                    exc_info=True,
                )

            if obj is not None:
                changes = compute_diff(before, after, display_before, display_after)
                meaningful_changes = _filter_skip_fields(model, changes)
                if meaningful_changes:
                    _create_audit_log(
                        action_type="update",
                        model=model,
                        object_id=str(pk),
                        object_repr=str(obj),
                        snapshot_before=before,
                        changes=changes,
                    )

        else:
            fields_in_update = list(kwargs.keys())
            auto_fields = _get_skip_fields(model)
            meaningful_fields = [f for f in fields_in_update if f not in auto_fields]

            if meaningful_fields:
                # Pure Python — no DB reads needed
                snapshot = compute_bulk_snapshot(objects_before, fields_in_update)
                changes = compute_bulk_diff(objects_before, kwargs)

                _create_audit_log(
                    action_type="bulk_update",
                    model=model,
                    object_repr=f"{model._meta.verbose_name} (bulk)",
                    snapshot_before=snapshot,
                    changes=changes,
                    is_bulk=True,
                    bulk_count=len(pks),
                )

    except Exception:
        logger.exception("Audit: Error in audited qs.update() for %s", model.__name__)

    return result


def audited_qs_delete(self):
    """Audited version of QuerySet.delete()."""
    model = self.model

    if not _should_audit_model(model):
        return _original_qs_delete(self)

    # Capture objects before delete — in atomic block
    pks = []
    objects_before = []
    try:
        with transaction.atomic():
            for obj in self.all():
                pks.append(str(obj.pk))
                data = serialize_instance(obj)
                data["__repr__"] = str(obj)[:255]
                objects_before.append(data)
    except Exception:
        logger.debug(
            "Audit: Could not capture objects before qs.delete() for %s",
            model.__name__,
            exc_info=True,
        )
        pks = []
        objects_before = []

    # Perform the delete
    result = _original_qs_delete(self)

    if not pks:
        return result

    # Post-delete audit (_create_audit_log handles its own savepoint)
    try:
        if len(pks) == 1:
            before = objects_before[0] if objects_before else {}
            obj_repr = before.pop("__repr__", "")

            _create_audit_log(
                action_type="delete",
                model=model,
                object_id=pks[0],
                object_repr=obj_repr,
                snapshot_before=before,
                changes={},
            )

        else:
            deleted_info = []
            for obj_data in objects_before:
                obj_repr = obj_data.pop("__repr__", "")
                deleted_info.append(
                    {
                        "id": obj_data.get("id"),
                        "repr": obj_repr,
                    }
                )

            _create_audit_log(
                action_type="bulk_delete",
                model=model,
                object_repr=f"{model._meta.verbose_name} (bulk)",
                snapshot_before={},
                changes={"deleted": deleted_info},
                is_bulk=True,
                bulk_count=len(pks),
            )

    except Exception:
        logger.exception("Audit: Error in audited qs.delete() for %s", model.__name__)

    return result


def audited_qs_bulk_create(self, objs, *args, **kwargs):
    """Audited version of QuerySet.bulk_create()."""
    model = self.model

    # Perform the bulk create first
    result = _original_qs_bulk_create(self, objs, *args, **kwargs)

    if not _should_audit_model(model):
        return result

    try:
        pks = [obj.pk for obj in result if obj.pk]
        _create_audit_log(
            action_type="bulk_create",
            model=model,
            object_repr=f"{model._meta.verbose_name} (bulk)",
            changes={"created": {"count": len(pks), "ids": pks}},
            is_bulk=True,
            bulk_count=len(pks),
        )
    except Exception:
        logger.exception("Audit: Error in audited bulk_create for %s", model.__name__)

    return result


def audited_qs_bulk_update(self, objs, fields, *args, **kwargs):
    """Audited version of QuerySet.bulk_update()."""
    model = self.model

    if not _should_audit_model(model):
        return _original_qs_bulk_update(self, objs, fields, *args, **kwargs)

    # Check if there are meaningful fields (non-auto fields)
    auto_fields = _get_skip_fields(model)
    meaningful_fields = [f for f in fields if f not in auto_fields]

    # Capture objects before update — in atomic block
    pks = []
    objects_before = []
    try:
        with transaction.atomic():
            pks = [obj.pk for obj in objs]
            objects_before = [
                serialize_instance(obj)
                for obj in model._default_manager.filter(pk__in=pks)
            ]
    except Exception:
        logger.debug(
            "Audit: Could not capture objects before bulk_update for %s",
            model.__name__,
            exc_info=True,
        )
        pks = []
        objects_before = []

    # Perform the bulk update
    result = _original_qs_bulk_update(self, objs, fields, *args, **kwargs)

    # Only log if there are meaningful changes
    if not pks or not meaningful_fields:
        return result

    # Post-update audit (_create_audit_log handles its own savepoint)
    try:
        update_values = {}
        if objs:
            for field in fields:
                update_values[field] = getattr(objs[0], field, None)

        snapshot = compute_bulk_snapshot(objects_before, list(fields))
        changes = compute_bulk_diff(objects_before, update_values)

        _create_audit_log(
            action_type="bulk_update",
            model=model,
            object_repr=f"{model._meta.verbose_name} (bulk)",
            snapshot_before=snapshot,
            changes=changes,
            is_bulk=True,
            bulk_count=len(pks),
        )

    except Exception:
        logger.exception("Audit: Error in audited bulk_update for %s", model.__name__)

    return result


def audited_model_save(self, *args, **kwargs):
    """Audited version of Model.save()."""
    model = self.__class__

    if not _should_audit_model(model):
        return _original_model_save(self, *args, **kwargs)

    # Detect create vs update by checking if object exists in DB
    # Wrapped in atomic block so a failure here doesn't poison the outer transaction
    before = {}
    display_before = {}
    is_create = True
    if self.pk is not None:
        try:
            with transaction.atomic():
                old_instance = model._default_manager.get(pk=self.pk)
                before, display_before = serialize_instance(
                    old_instance, include_display=True
                )
                is_create = False
        except model.DoesNotExist:
            pass  # Object doesn't exist yet, it's a create
        except Exception:
            logger.debug(
                "Audit: Could not capture before state for %s.save()",
                model.__name__,
                exc_info=True,
            )

    # Perform the save
    result = _original_model_save(self, *args, **kwargs)

    # Post-save: capture "after" state — in atomic block so FK display queries can't poison the transaction
    try:
        with transaction.atomic():
            after, display_after = serialize_instance(self, include_display=True)
    except Exception:
        logger.debug(
            "Audit: Could not capture after state for %s.save()",
            model.__name__,
            exc_info=True,
        )
        return result

    # Diff computation (pure Python) + _create_audit_log (has its own savepoint)
    try:
        if is_create:
            changes = {
                key: {"old": None, "new": value}
                for key, value in after.items()
                if value is not None
            }
            # Add display values for FK fields on create
            for key in changes:
                if key in display_after:
                    changes[key]["new_display"] = display_after[key]
            # Only log if there are meaningful changes (non-auto fields)
            meaningful_changes = _filter_skip_fields(model, changes)
            if meaningful_changes:
                _create_audit_log(
                    action_type="create",
                    model=model,
                    object_id=str(self.pk),
                    object_repr=str(self),
                    snapshot_before={},
                    changes=changes,
                )
        else:
            changes = compute_diff(before, after, display_before, display_after)
            # Only log if there are meaningful changes (non-auto fields)
            meaningful_changes = _filter_skip_fields(model, changes)
            if meaningful_changes:
                _create_audit_log(
                    action_type="update",
                    model=model,
                    object_id=str(self.pk),
                    object_repr=str(self),
                    snapshot_before=before,
                    changes=changes,
                )
    except Exception:
        logger.exception("Audit: Error in Model.save() for %s", model.__name__)

    return result


def audited_model_delete(self, *args, **kwargs):
    """Audited version of Model.delete()."""
    model = self.__class__

    if not _should_audit_model(model):
        return _original_model_delete(self, *args, **kwargs)

    # Capture before state — in atomic block so str(self) FK lookups can't poison the transaction
    before = {}
    obj_repr = ""
    pk = str(self.pk) if self.pk is not None else ""
    try:
        with transaction.atomic():
            before = serialize_instance(self)
            obj_repr = str(self)[:255]
    except Exception:
        logger.debug(
            "Audit: Could not capture object before delete for %s",
            model.__name__,
            exc_info=True,
        )

    # Perform the delete
    result = _original_model_delete(self, *args, **kwargs)

    try:
        _create_audit_log(
            action_type="delete",
            model=model,
            object_id=pk,
            object_repr=obj_repr,
            snapshot_before=before,
            changes={},
        )
    except Exception:
        logger.exception("Audit: Error in Model.delete() for %s", model.__name__)

    return result


def install_manager_hooks():
    """
    Install the QuerySet and Model hooks for audit logging.

    Hooks:
    - Model.save() - handles create and update for single objects
    - Model.delete() - handles single deletes
    - QuerySet.update() - handles bulk updates (bypasses Model.save)
    - QuerySet.delete() - handles bulk deletes (bypasses Model.delete)
    - QuerySet.bulk_create() - handles bulk creates (bypasses Model.save)
    - QuerySet.bulk_update() - handles bulk updates (bypasses Model.save)

    M2M changes are audited via the through model (create/delete on the junction table).

    Note: QuerySet.create() is NOT hooked because it calls Model.save() internally.

    This must be called in AppConfig.ready().
    """
    global _original_qs_update, _original_qs_delete
    global _original_qs_bulk_create, _original_qs_bulk_update
    global _original_model_save, _original_model_delete
    global _hooks_installed

    if _hooks_installed:
        return

    from django.db.models import Model
    from django.db.models.query import QuerySet

    # Patch QuerySet methods for bulk operations (these bypass Model methods)
    _original_qs_update = QuerySet.update
    _original_qs_delete = QuerySet.delete
    _original_qs_bulk_create = QuerySet.bulk_create
    _original_qs_bulk_update = QuerySet.bulk_update

    QuerySet.update = audited_qs_update
    QuerySet.delete = audited_qs_delete
    QuerySet.bulk_create = audited_qs_bulk_create
    QuerySet.bulk_update = audited_qs_bulk_update

    # Patch Model methods for instance operations
    _original_model_save = Model.save
    _original_model_delete = Model.delete

    Model.save = audited_model_save
    Model.delete = audited_model_delete

    _hooks_installed = True


def uninstall_manager_hooks():
    """Restore the original QuerySet and Model methods."""
    global _original_qs_update, _original_qs_delete
    global _original_qs_bulk_create, _original_qs_bulk_update
    global _original_model_save, _original_model_delete
    global _hooks_installed

    if not _hooks_installed:
        return

    from django.db.models import Model
    from django.db.models.query import QuerySet

    # Restore QuerySet methods
    if _original_qs_update:
        QuerySet.update = _original_qs_update
    if _original_qs_delete:
        QuerySet.delete = _original_qs_delete
    if _original_qs_bulk_create:
        QuerySet.bulk_create = _original_qs_bulk_create
    if _original_qs_bulk_update:
        QuerySet.bulk_update = _original_qs_bulk_update

    # Restore Model methods
    if _original_model_save:
        Model.save = _original_model_save
    if _original_model_delete:
        Model.delete = _original_model_delete

    _original_qs_update = None
    _original_qs_delete = None
    _original_qs_bulk_create = None
    _original_qs_bulk_update = None
    _original_model_save = None
    _original_model_delete = None
    _hooks_installed = False
