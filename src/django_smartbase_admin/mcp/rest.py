"""REST dispatch helpers for SBAdmin MCP tools.

Host projects provide authentication and then call the same guarded tool
methods used by the MCP transport.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils.module_loading import import_string
from django_smartbase_admin.mcp.mcp import SBAdminTools
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class SBAdminMCPRestAuthenticator(BaseAuthentication):
    """Project hook for mapping a REST request to the acting user."""

    def authenticate(self, request: Request, **kwargs) -> tuple[Any, Any] | Any | None:
        raise NotImplementedError


def resolve_sbadmin_mcp_rest_authenticator(
    authenticator: SBAdminMCPRestAuthenticator | type | str | None = None,
) -> SBAdminMCPRestAuthenticator:
    """Resolve the configured REST authenticator.

    Host projects can still pass an authenticator instance to ``as_view()``,
    but the normal package URLconf reads ``SBADMIN_MCP_REST_AUTHENTICATOR``
    from settings. The setting may be an import path, a class, or an instance.
    """
    if authenticator is None:
        authenticator = getattr(settings, "SBADMIN_MCP_REST_AUTHENTICATOR", None)
    if authenticator is None:
        raise ImproperlyConfigured(
            "Set SBADMIN_MCP_REST_AUTHENTICATOR to an "
            "SBAdminMCPRestAuthenticator import path, class, or instance."
        )
    if isinstance(authenticator, str):
        authenticator = import_string(authenticator)
    if isinstance(authenticator, type):
        authenticator = authenticator()
    if not hasattr(authenticator, "authenticate"):
        raise ImproperlyConfigured(
            "SBADMIN_MCP_REST_AUTHENTICATOR must provide an authenticate() method."
        )
    return authenticator


def is_guarded_mcp_tool(method) -> bool:
    return callable(method) and bool(getattr(method, "sbadmin_mcp_tool", False))


def resolve_guarded_mcp_tool(toolset, tool_name: str):
    method = getattr(toolset, tool_name, None)
    if not is_guarded_mcp_tool(method):
        raise Http404
    return method


def call_sbadmin_mcp_tool(
    *,
    request: Request,
    tool_name: str,
    arguments: dict | None = None,
    toolset_cls=SBAdminTools,
):
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ParseError("Tool arguments must be a JSON object.")

    toolset = toolset_cls(request=request)
    method = resolve_guarded_mcp_tool(toolset, tool_name)
    return method(**arguments)


class SBAdminMCPToolAPIView(APIView):
    """Reusable REST endpoint for guarded SBAdmin MCP tool calls.

    Include ``django_smartbase_admin.mcp.urls`` and configure
    ``SBADMIN_MCP_REST_AUTHENTICATOR`` in settings, or pass
    ``authenticator=...`` from ``as_view()``. The authenticator owns
    project-specific credentials; this view owns only dispatching to guarded
    SBAdmin MCP tools.
    """

    authentication_classes: tuple = ()
    permission_classes: tuple = ()
    authenticator: SBAdminMCPRestAuthenticator | None = None
    toolset_cls = SBAdminTools

    def get_authenticator(self) -> SBAdminMCPRestAuthenticator:
        return resolve_sbadmin_mcp_rest_authenticator(self.authenticator)

    def authenticate_rest_request(self, request: Request, **kwargs) -> Any:
        identity = self.get_authenticator().authenticate(request, **kwargs)
        if identity is None:
            raise AuthenticationFailed("Invalid MCP REST credentials.")
        if isinstance(identity, tuple):
            return identity[0]
        return identity

    def post(self, request: Request, tool_name: str, **kwargs) -> Response:
        try:
            request.user = self.authenticate_rest_request(request, **kwargs)
            result = call_sbadmin_mcp_tool(
                request=request,
                tool_name=tool_name,
                arguments=request.data,
                toolset_cls=self.toolset_cls,
            )
        except AuthenticationFailed:
            return Response(
                {"detail": "Invalid MCP REST credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except (PermissionDenied, PermissionError):
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        except (Http404, LookupError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)
