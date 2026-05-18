"""Test-only SBAdmin configuration classes.

``EmptySBAdminConfiguration`` is the default for the whole test run — it
returns the stock ``SBAdminRoleConfiguration`` so behavior mirrors
production (Django model permissions). MCP unit tests that need to drive
per-case permission outcomes opt into ``MCPSBAdminConfiguration`` via
``@override_settings(SB_ADMIN_CONFIGURATION=...)``; it returns
``MCPToolTestConfig``, whose class-level ``view_permission_for`` they
mutate.
"""

from django_smartbase_admin.engine.configuration import (
    SBAdminConfigurationBase,
    SBAdminRoleConfiguration,
)


class MCPToolTestConfig(SBAdminRoleConfiguration):
    """Role configuration with overridable per-test view permissions.

    ``SBAdminRoleConfiguration`` uses a Singleton metaclass, so all tests
    share one instance per subclass; ``view_permission_for`` and
    ``restrict_qs`` are exposed as *class* attributes and test ``setUp`` /
    ``tearDown`` mutate them per case.

    * ``view_permission_for``: ``None`` means allow-all (default
      positive-path); a set means "only these models".
    * ``restrict_qs``: ``None`` means no row-level restriction (passthrough);
      a callable ``(qs, model) -> qs`` narrows querysets the same way
      production ``SBAdminRoleConfiguration.restrict_queryset`` would.
    """

    view_permission_for: set | None = None
    restrict_qs = None

    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        if type(self).view_permission_for is None:
            return True
        return model in type(self).view_permission_for

    def restrict_queryset(
        self,
        qs,
        model,
        request,
        request_data,
        global_filter=True,
        global_filter_data_map=None,
    ):
        if type(self).restrict_qs is None:
            return qs
        return type(self).restrict_qs(qs, model)


class EmptySBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return SBAdminRoleConfiguration()


class MCPSBAdminConfiguration(SBAdminConfigurationBase):
    """Returns ``MCPToolTestConfig`` so ``delegate_to_action`` (which
    rebuilds ``request_data`` and pulls the configuration fresh from
    settings) sees the same singleton the test fixture pre-populates."""

    def get_configuration_for_roles(self, user_roles):
        return MCPToolTestConfig()
