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
        return configuration_class(
            request_data=request_data
        ).get_configuration_for_roles(user_roles)

    @classmethod
    def get_view_url_identifier(cls, view_id):
        if view_id:
            return slugify(view_id)
        else:
            return view_id


class SBAdminUserConfigurationService(object):
    @classmethod
    def get_user_config(cls, request):
        """Delegate to the configuration class's get_user_config method."""
        configuration_class = import_string(settings.SB_ADMIN_CONFIGURATION)
        return configuration_class.get_user_config(request)

    @classmethod
    def get_saved_views(cls, request, view_id):
        """Delegate to the configuration class's get_saved_views method."""
        configuration_class = import_string(settings.SB_ADMIN_CONFIGURATION)
        return configuration_class.get_saved_views(request, view_id)

    @classmethod
    def create_or_update_saved_view(cls, request, view_id, config_id, config_name, url_params):
        """Delegate to the configuration class's create_or_update_saved_view method."""
        configuration_class = import_string(settings.SB_ADMIN_CONFIGURATION)
        return configuration_class.create_or_update_saved_view(
            request, view_id, config_id, config_name, url_params
        )

    @classmethod
    def delete_saved_view(cls, request, view_id, config_id):
        """Delegate to the configuration class's delete_saved_view method."""
        configuration_class = import_string(settings.SB_ADMIN_CONFIGURATION)
        return configuration_class.delete_saved_view(request, view_id, config_id)
