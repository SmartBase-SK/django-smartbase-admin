from django.conf import settings
from django.utils.module_loading import import_string
from django.utils.text import slugify


class SBAdminConfigurationService(object):
    @classmethod
    def get_configuration(cls, request_data):
        configuration_class = import_string(settings.SB_ADMIN_CONFIGURATION)
        user_roles = ["ANONYMOUS"]
        if not request_data.user.is_anonymous:
            user_roles = request_data.user.groups.values_list("name", flat=True)
        return configuration_class().get_configuration_for_roles(user_roles)

    @classmethod
    def get_view_url_identifier(cls, view_id):
        if view_id:
            return slugify(view_id)
        else:
            return view_id
