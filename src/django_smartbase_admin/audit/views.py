"""
View helpers for audit history.
"""

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect
from django.urls import reverse

from django_smartbase_admin.services.views import SBAdminViewService


def _get_audit_view_id():
    """Get the view ID for AdminAuditLog dynamically from model meta."""
    from django_smartbase_admin.audit.models import AdminAuditLog

    return SBAdminViewService.get_model_path(AdminAuditLog)


def get_audit_history_url(obj) -> str:
    """
    Get the URL to view audit history for an object in the admin.

    Args:
        obj: The model instance.

    Returns:
        URL string to the audit log admin filtered for this object.
    """
    content_type = ContentType.objects.get_for_model(obj)
    view_id = _get_audit_view_id()

    # Build filter value in [{"value": ..., "label": ...}] format
    # Value encodes content_type_id:object_id for the OR filter logic
    # Label shows model name and object representation for nice display
    model_name = content_type.model_class()._meta.verbose_name.title()
    obj_repr = str(obj)[:50]  # Truncate long representations

    filter_data = {
        "object_history": [
            {
                "value": f"{content_type.pk}:{obj.pk}",
                "label": f"{model_name}: {obj_repr}",
            }
        ],
    }

    # Build URL with SBAdmin params format
    base_url = reverse(f"sb_admin:{view_id}_changelist")
    params_str = SBAdminViewService.build_list_params_url(view_id, filter_data)

    return f"{base_url}?{params_str}"


def get_audit_model_history_url(model_class) -> str:
    """
    Get the URL to view audit history for all changes to a model type.

    Args:
        model_class: The Django model class.

    Returns:
        URL string to the audit log admin filtered for this model's content type.
    """
    content_type = ContentType.objects.get_for_model(model_class)
    view_id = _get_audit_view_id()

    filter_data = {
        "content_type": [
            {
                "value": content_type.pk,
                "label": f"{content_type.app_label}.{content_type.model}",
            }
        ],
    }

    base_url = reverse(f"sb_admin:{view_id}_changelist")
    params_str = SBAdminViewService.build_list_params_url(view_id, filter_data)

    return f"{base_url}?{params_str}"


def redirect_to_audit_history(request, obj):
    """
    Redirect to the audit history view for an object.

    This can be used as a replacement for the standard Django history view.
    """
    url = get_audit_history_url(obj)
    return redirect(url)


def redirect_to_audit_model_history(request, model_class):
    """
    Redirect to the audit history view for all changes to a model type.

    This can be used to show the full history of a model from the list view.
    """
    url = get_audit_model_history_url(model_class)
    return redirect(url)
