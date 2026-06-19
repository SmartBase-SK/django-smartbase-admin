from django import template

from django_smartbase_admin.messaging.services import SBAdminMessagingService
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

register = template.Library()


@register.filter
def message_type_badge(type_key):
    """Render the badge for a message type key (resolves config from the request)."""
    try:
        request = SBAdminThreadLocalService.get_request()
    except LookupError:
        request = None
    messaging_config = (
        SBAdminMessagingService.get_messaging_config(request) if request else None
    )
    return SBAdminMessagingService.render_message_type_badge(
        type_key, messaging_config
    )
