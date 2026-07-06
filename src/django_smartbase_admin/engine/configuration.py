from django.contrib.auth import get_permission_codename
from django.contrib.auth.views import LoginView
from django.db.models import Q

from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import SBAdminCustomAction
from django_smartbase_admin.engine.const import (
    GLOBAL_FILTER_DATA_KEY,
    FilterVersions,
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


class SBAdminWhoamiConfig:
    """MCP pointer to the current user's profile change view."""

    def __init__(self, view_id, object_id_getter=None):
        self.view_id = view_id
        self.object_id_getter = object_id_getter or self.get_default_object_id

    @staticmethod
    def get_default_object_id(request):
        return getattr(request.user, "pk", None)


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
    admin_title = "SBAdmin"
    # List of SBAdminPlugin subclasses that participate in every list
    # view's data pipeline and Tabulator definition. See
    # ``plugins/base.py`` for the protocol. Each plugin hook is expected
    # to self-guard based on admin config (e.g. ``sbadmin_nested``).
    plugins: list = []
    default_list_sticky_header_and_footer = True
    # Minimum number of pages from which a separate 'jump to page' input
    # is shown next to list pagination. None disables the input entirely.
    list_pagination_page_input_min_pages = 50
    enable_url_compression = True
    mcp_readonly = False
    link_history_to_audit = True
    messaging_config = None
    mcp_whoami_sbadmin = None

    def __init__(
        self,
        default_view=None,
        registered_views=None,
        menu_items=None,
        global_filter_form=None,
        filters_version=None,
        default_color_scheme=None,
        login_view_class=None,
        admin_title=None,
        plugins=None,
        default_list_sticky_header_and_footer=None,
        list_pagination_page_input_min_pages=None,
        enable_url_compression=None,
        mcp_readonly=None,
        link_history_to_audit=None,
        messaging_config=None,
        mcp_whoami_sbadmin=None,
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
        self.admin_title = admin_title or self.admin_title
        # Copy the class-level list to avoid accidental cross-instance
        # mutation when subclasses assign ``plugins = [...]``.
        self.plugins = list(plugins if plugins is not None else self.plugins)
        if default_list_sticky_header_and_footer is not None:
            self.default_list_sticky_header_and_footer = (
                default_list_sticky_header_and_footer
            )
        if list_pagination_page_input_min_pages is not None:
            self.list_pagination_page_input_min_pages = (
                list_pagination_page_input_min_pages
            )
        self.enable_url_compression = (
            enable_url_compression
            if enable_url_compression is not None
            else self.enable_url_compression
        )
        self.mcp_readonly = (
            mcp_readonly if mcp_readonly is not None else self.mcp_readonly
        )
        self.link_history_to_audit = (
            link_history_to_audit
            if link_history_to_audit is not None
            else self.link_history_to_audit
        )
        self.messaging_config = (
            messaging_config if messaging_config is not None else self.messaging_config
        )
        self.mcp_whoami_sbadmin = (
            mcp_whoami_sbadmin
            if mcp_whoami_sbadmin is not None
            else self.mcp_whoami_sbadmin
        )

    def init_registered_views(self):
        registered_views = []
        for view in self.registered_views:
            registered_views.append(view)
            view.init_view_static(self, None, sb_admin_site)
            sub_views = view.get_sub_views(self)
            if sub_views:
                registered_views.extend(sub_views)
        self.registered_views = registered_views

    def init_menu_items(self):
        for menu_item in self.menu_items:
            menu_item.init_menu_item_static(self.view_map)

    def init_menu_items_dynamic(self, request, request_data):
        menu_items = []
        for item in self.menu_items:
            item_dict, _item_active = item.process_and_serialize(request, request_data)
            if item_dict is not None:
                menu_items.append(item_dict)
        request_data.menu_items = menu_items

    def get_default_view_id(self, request, request_data):
        if self.default_view:
            return self.default_view.get_view_id()
        return self.get_first_menu_view_id(request, request_data)

    def get_first_menu_view_id(self, request, request_data):
        for item in self.menu_items:
            view_id = self._first_permitted_menu_view_id(item, request, request_data)
            if view_id:
                return view_id
        return None

    def _first_permitted_menu_view_id(self, item, request, request_data):
        if item.has_menu_permission(request, request_data) and item.get_view_id():
            return item.get_view_id()
        for sub_item in item.sub_items:
            view_id = self._first_permitted_menu_view_id(
                sub_item, request, request_data
            )
            if view_id:
                return view_id
        return None

    def init_view_map(self):
        self.view_map.update({view.get_id(): view for view in self.registered_views})
        self.view_map.update(
            {
                view.get_id(): view
                for model, view in sb_admin_site._registry.items()
                if hasattr(view, "get_id")
            }
        )
        try:
            from cms.plugin_pool import plugin_pool

            from django_smartbase_admin.integration.django_cms import (
                DjangoCMSPluginSBAdmin,
            )

            for name, view in plugin_pool.plugins.items():
                if not (
                    isinstance(view, type)
                    and issubclass(view, DjangoCMSPluginSBAdmin)
                    and hasattr(view, "get_id")
                ):
                    continue
                view_instance = view(view.model, sb_admin_site)
                self.view_map[view_instance.get_id()] = view_instance
                view_instance.init_view_static(self, view_instance.model, sb_admin_site)
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
        self.view_map = {}
        self.init_registered_views()
        self.init_view_map()
        self.init_model_admin_view_map()
        self.init_menu_items()

    def dynamically_register_autocomplete_view(self, view):
        """Register into the current request map when a request is active."""
        try:
            from django_smartbase_admin.services.thread_local import (
                SBAdminThreadLocalService,
            )

            request = SBAdminThreadLocalService.get_request()
        except LookupError:
            return
        request_data = getattr(request, "request_data", None)
        if request_data is not None:
            request_data.register_autocomplete_view(view)

    def get_whoami_target(self, request):
        """Return the current user's configured profile target for MCP."""
        config = self.mcp_whoami_sbadmin
        user = getattr(request, "user", None)
        if not config or not getattr(user, "is_authenticated", False):
            return None

        view_id = getattr(config, "view_id", None)
        if not view_id:
            return None
        view = self.view_map.get(view_id)
        if view is None:
            raise LookupError(f"No SBAdmin view registered with view_id={view_id!r}.")

        object_id_getter = getattr(config, "object_id_getter", None)
        object_id = object_id_getter(request) if callable(object_id_getter) else None
        if object_id is None:
            return None

        return {"view_id": view_id, "object_id": str(object_id)}

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

    def get_action_permission(self, action):
        return getattr(action, "permission", None) or "change"

    def has_action_permission(self, request, request_data, view, model, obj, action):
        if model:
            permission = self.get_action_permission(action)
            if self.is_mcp_readonly_request(request) and permission != "view":
                return False
            return self.has_permission(
                request, request_data, view, model, obj, permission
            )
        return request.user.is_staff

    def is_mcp_readonly_request(self, request):
        return (
            self.mcp_readonly
            and getattr(request, "is_mcp", False)
            and not request.user.is_superuser
        )

    def is_mcp_readonly_permission(self, request, permission):
        if not self.is_mcp_readonly_request(request):
            return False
        if isinstance(permission, SBAdminCustomAction):
            return self.get_action_permission(permission) != "view"
        return permission in ("add", "change", "delete")

    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        if self.is_mcp_readonly_permission(request, permission):
            return False
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

    def get_admin_title(self):
        return self.admin_title
