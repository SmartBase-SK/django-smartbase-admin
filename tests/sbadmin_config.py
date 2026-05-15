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
    share one instance per subclass; ``view_permission_for`` is exposed as
    a *class* attribute and test ``setUp`` mutates it per case. ``None``
    means allow-all (the typical positive-path default); a set means
    "only these models".
    """

    view_permission_for: set | None = None

    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        if type(self).view_permission_for is None:
            return True
        return model in type(self).view_permission_for


class EmptySBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return SBAdminRoleConfiguration()


class MCPSBAdminConfiguration(SBAdminConfigurationBase):
    """Returns ``MCPToolTestConfig`` so ``delegate_to_action`` (which
    rebuilds ``request_data`` and pulls the configuration fresh from
    settings) sees the same singleton the test fixture pre-populates."""

    def get_configuration_for_roles(self, user_roles):
        return MCPToolTestConfig()
