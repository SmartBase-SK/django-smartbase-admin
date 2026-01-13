from django.contrib.auth import get_permission_codename
from django.contrib.auth.views import LoginView
from django.db.models import Q

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.engine.const import (
    GLOBAL_FILTER_DATA_KEY,
    FilterVersions,
    Action,
)
from django_smartbase_admin.models import (
    ColorScheme,
    SBAdminListViewConfiguration,
    SBAdminUserConfiguration,
)
from django_smartbase_admin.utils import to_list, is_modal


class SBAdminConfigurationBase(object):
    request_data = None

    def __init__(self, request_data=None):
        super().__init__()
        self.request_data = request_data

    def get_configuration_for_roles(self, user_roles):
        raise NotImplementedError

    # User configuration hooks - override these methods to customize user identification
    # (e.g., use email instead of user_id for OAuth/external auth scenarios)

    @classmethod
    def get_user_config(cls, request):
        """
        Get or create user configuration (e.g., color scheme preferences).

        Override this method to customize user identification. Default uses user_id.

        Example for email-based users::

            @classmethod
            def get_user_config(cls, request):
                from myapp.models import MyUserConfig
                email = getattr(request.user, "email", None)
                if not email:
                    return MyUserConfig(email="anonymous", color_scheme=ColorScheme.AUTO.value)
                config, _ = MyUserConfig.objects.get_or_create(
                    email=email,
                    defaults={"color_scheme": request.request_data.configuration.default_color_scheme},
                )
                return config
        """
        if not request.user or request.user.is_anonymous:
            return None
        user_config, _ = SBAdminUserConfiguration.objects.get_or_create(
            defaults={
                "color_scheme": request.request_data.configuration.default_color_scheme
            },
            user_id=request.user.id,
        )
        return user_config

    @classmethod
    def get_saved_views(cls, request, view_id):
        """
        Get saved views for the current user and view.

        Override this method to customize user identification. Default uses user_id.
        Returns a list of dicts with keys: id, name, url_params, view (view_id).

        Example for email-based users::

            @classmethod
            def get_saved_views(cls, request, view_id):
                from myapp.models import MySavedView
                email = getattr(request.user, "email", None)
                if not email:
                    return []
                return list(
                    MySavedView.objects.filter(email=email, view_id=view_id)
                    .values("id", "name", "config", "view_id")
                )
        """
        if not request.user or request.user.is_anonymous:
            return []
        return list(
            SBAdminListViewConfiguration.objects.by_user_id(request.user.id)
            .by_view_action_modifier(view=view_id)
            .values()
        )

    @classmethod
    def create_or_update_saved_view(
        cls, request, view_id, config_id, config_name, url_params
    ):
        """
        Create or update a saved view for the current user.

        Override this method to customize user identification. Default uses user_id.
        Returns the created/updated saved view object.

        Example for email-based users::

            @classmethod
            def create_or_update_saved_view(cls, request, view_id, config_id, config_name, url_params):
                from myapp.models import MySavedView
                email = getattr(request.user, "email", None)
                if not email:
                    return None
                config_params = {}
                if config_id:
                    config_params["id"] = config_id
                if config_name:
                    config_params["name"] = config_name
                saved_view, _ = MySavedView.objects.update_or_create(
                    email=email,
                    **config_params,
                    defaults={"config": {"url_params": url_params}, "view_id": view_id},
                )
                return saved_view
        """
        if not request.user or request.user.is_anonymous:
            return None
        config_params = {}
        if config_id:
            config_params["id"] = config_id
        elif config_name:
            config_params["name"] = config_name
        if not config_params:
            return None
        saved_view, _ = SBAdminListViewConfiguration.objects.update_or_create(
            user_id=request.user.id,
            **config_params,
            defaults={
                "url_params": url_params,
                "view": view_id,
                "action": None,
                "modifier": None,
            },
        )
        return saved_view

    @classmethod
    def delete_saved_view(cls, request, view_id, config_id):
        """
        Delete a saved view for the current user.

        Override this method to customize user identification. Default uses user_id.

        Example for email-based users::

            @classmethod
            def delete_saved_view(cls, request, view_id, config_id):
                from myapp.models import MySavedView
                email = getattr(request.user, "email", None)
                if not email or not config_id:
                    return
                MySavedView.objects.filter(
                    email=email, id=config_id, view_id=view_id
                ).delete()
        """
        if not request.user or request.user.is_anonymous or not config_id:
            return
        SBAdminListViewConfiguration.objects.by_user_id(request.user.id).by_id(
            config_id
        ).by_view_action_modifier(view=view_id).delete()


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class SBAdminRoleConfiguration(metaclass=Singleton):
    default_view = None
    registered_views = None
    view_map = None
    autocomplete_map = None
    menu_items = None
    global_filter_form = None
    filters_version = FilterVersions.FILTERS_VERSION_1
    default_color_scheme = ColorScheme.AUTO
    login_view_class = LoginView

    def __init__(
        self,
        default_view=None,
        registered_views=None,
        menu_items=None,
        global_filter_form=None,
        filters_version=None,
        default_color_scheme=None,
        login_view_class=None,
    ) -> None:
        super().__init__()
        self.default_view = default_view or self.default_view or []
        self.registered_views = registered_views or self.registered_views or []
        self.menu_items = menu_items or self.menu_items or []
        self.global_filter_form = global_filter_form or self.global_filter_form
        self.init_configuration_static()
        self.autocomplete_map = {}
        self.filters_version = filters_version or self.filters_version
        self.default_color_scheme = default_color_scheme or self.default_color_scheme
        self.login_view_class = login_view_class or self.login_view_class

    def init_registered_views(self):
        registered_views = []
        for view in self.registered_views:
            registered_views.append(view)
            sub_views = view.get_sub_views(self)
            if sub_views:
                registered_views.extend(sub_views)
        self.registered_views = registered_views

    def init_menu_items(self):
        for menu_item in self.menu_items:
            menu_item.init_menu_item_static(self.view_map)

    def init_menu_items_dynamic(self, request, request_data):
        menu_items = [
            item.process_and_serialize(request, request_data)[0]
            for item in self.menu_items
        ]
        request_data.menu_items = menu_items

    def init_view_map(self):
        self.view_map = {view.get_id(): view for view in self.registered_views}
        self.view_map.update(
            {
                view.get_id(): view
                for model, view in sb_admin_site._registry.items()
                if hasattr(view, "get_id")
            }
        )
        try:
            from cms.plugin_pool import plugin_pool

            for name, view in plugin_pool.plugins.items():
                if hasattr(view, "get_id"):
                    view_instance = view(view.model, sb_admin_site)
                    self.view_map[view_instance.get_id()] = view_instance
                    view_instance.init_view_static(
                        self, view_instance.model, sb_admin_site
                    )
        except ImportError:
            pass

    def init_model_admin_view_map(self):
        for model, admin_view in sb_admin_site._registry.items():
            admin_view.init_view_static(self, model, sb_admin_site)

    def get_global_filter_form_class(self, request):
        return self.global_filter_form

    def init_global_filter_form_instance(self, request):
        global_filter_form_class = self.get_global_filter_form_class(request)
        if global_filter_form_class:
            form_instance = global_filter_form_class(
                data=request.request_data.global_filter
            )
            if form_instance.is_valid():
                request.request_data.set_global_filter_instance(form_instance)
            else:
                request.session[GLOBAL_FILTER_DATA_KEY] = None
                request.request_data.set_global_filter_instance(
                    global_filter_form_class()
                )

    def init_configuration_dynamic(self, request, request_data):
        self.init_global_filter_form_instance(request)
        self.init_menu_items_dynamic(request, request_data)

    def init_configuration_static(self):
        self.init_registered_views()
        self.init_view_map()
        self.init_model_admin_view_map()
        self.init_menu_items()

    def dynamically_register_autocomplete_view(self, view):
        self.autocomplete_map[view.get_id()] = view

    def restrict_queryset(
        self,
        qs,
        model,
        request,
        request_data,
        global_filter=True,
        global_filter_data_map=None,
    ):
        return qs

    def has_action_permission(self, request, request_data, view, model, obj, action):
        if model:
            if action.action_id == Action.BULK_DELETE.value:
                return view.has_delete_permission(request, obj)
            return self.has_permission(
                request, request_data, view, model, obj, "view"
            ) or self.has_permission(request, request_data, view, model, obj, "change")
        return request.user.is_staff

    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        if isinstance(permission, SBAdminCustomAction):
            return self.has_action_permission(
                request, request_data, view, model, obj, permission
            )
        if model:
            opts = model._meta
            codename = get_permission_codename(permission, opts)
            allowed = request.user.has_perm("%s.%s" % (opts.app_label, codename))
            if not allowed and opts.auto_created:
                opts = opts.auto_created._meta
                return request.user.has_perm(
                    "%s.%s"
                    % (opts.app_label, get_permission_codename(permission, opts))
                )
            return allowed
        return request.user.is_staff

    def get_autocomplete_widget(
        self, view, request, form_field, db_field, model, multiselect=False
    ):
        from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

        return SBAdminAutocompleteWidget(
            form_field, model=model, multiselect=multiselect
        )

    def get_filter_widget(self, field, default_widget):
        return default_widget

    def get_form_field_widget_class(
        self, view, request, form_field, db_field, default_widget_class
    ):
        return default_widget_class

    def apply_global_filter_to_queryset(
        self, qs, request, request_data, global_filter_data_map
    ):
        global_filter_data_map = global_filter_data_map or {}
        global_filter_data_map = {
            value: key for key, value in global_filter_data_map.items()
        }
        filter_query = Q()
        global_filter_fields = request_data.global_filter_instance or []
        include_all_values_for_empty_fields = getattr(
            request_data.global_filter_instance,
            "include_all_values_for_empty_fields",
            None,
        )
        for field in global_filter_fields:
            field_value = None
            try:
                field_value = field.value()
            except:
                pass
            if (
                include_all_values_for_empty_fields
                and field.name in include_all_values_for_empty_fields
                and not field_value
            ):
                continue
            field_value = to_list(field_value)
            global_filter_mapped_filter_key = global_filter_data_map.get(
                field.name, None
            )
            if global_filter_mapped_filter_key:
                filter_query &= Q(**{f"{global_filter_mapped_filter_key}": field_value})
        return qs.filter(filter_query)

    def process_global_filter_response(self, response, request):
        return response

    def autocomplete_show_related_buttons(
        self,
        related_model,
        field_name,
        current_view,
        request,
    ) -> bool:
        return not is_modal(request)
