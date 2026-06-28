"""REST dispatch helpers for SBAdmin MCP tools.

Host projects provide authentication and then call the same guarded tool
methods used by the MCP transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django_smartbase_admin.mcp.mcp import SBAdminTools
from mcp.server.fastmcp.tools.base import Tool
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ParseError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


@dataclass(frozen=True)
class SBAdminMCPRestIdentity:
    user: Any


class SBAdminMCPRestAuthenticator:
    """Project hook for mapping a REST request to the acting user."""

    def authenticate(
        self, request: Request, **kwargs
    ) -> SBAdminMCPRestIdentity | Any | None:
        raise NotImplementedError


def is_guarded_mcp_tool(method) -> bool:
    return callable(method) and bool(getattr(method, "sbadmin_mcp_tool", False))


def resolve_guarded_mcp_tool(toolset, tool_name: str):
    method = getattr(toolset, tool_name, None)
    if not is_guarded_mcp_tool(method):
        raise Http404
    return method


def describe_sbadmin_mcp_tool(method) -> dict:
    tool = Tool.from_function(method)
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "input_schema": tool.parameters,
        "output_schema": tool.output_schema,
        "annotations": tool.annotations,
    }


def list_sbadmin_mcp_tools(*, request: Request, toolset_cls=SBAdminTools) -> dict:
    toolset = toolset_cls(request=request)
    tools = []
    for name in dir(toolset):
        if name.startswith("_"):
            continue
        method = getattr(toolset, name)
        if is_guarded_mcp_tool(method):
            tools.append(describe_sbadmin_mcp_tool(method))
    tools.sort(key=lambda tool: tool["name"])
    return {"tools": tools}


def get_sbadmin_mcp_rest_capabilities(*, toolset_cls=SBAdminTools) -> dict:
    return {
        "protocol": "sbadmin-mcp-rest",
        "mcp_protocol_version": "2025-06-18",
        "server_info": {
            "name": "django-smartbase-admin",
            "title": "Django SmartBase Admin MCP REST",
        },
        "capabilities": {
            "tools": {
                "list": True,
                "call": True,
                "list_changed": False,
            },
            "resources": {
                "list": False,
                "read": False,
                "templates": False,
                "subscribe": False,
            },
            "prompts": {
                "list": False,
                "get": False,
            },
            "completions": False,
            "logging": False,
            "progress": False,
            "cancellation": False,
        },
        "instructions": (
            "Call GET tools/ to discover guarded MCP tools, then POST "
            "tools/{tool_name}/ with a JSON object matching input_schema. "
            "Start with list_admins to discover admin view_id, fields, filters, "
            "actions, widget shapes, and related handles."
        ),
    }


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

    Subclass this view or pass ``authenticator=...`` from ``as_view()``.
    The authenticator owns project-specific credentials; this view owns only
    dispatching to guarded SBAdmin MCP tools.
    """

    authentication_classes: tuple = ()
    permission_classes: tuple = ()
    authenticator: SBAdminMCPRestAuthenticator | None = None
    toolset_cls = SBAdminTools

    def get_authenticator(self) -> SBAdminMCPRestAuthenticator:
        if self.authenticator is None:
            raise NotImplementedError("Set authenticator on SBAdminMCPToolAPIView.")
        return self.authenticator

    def authenticate_rest_request(self, request: Request, **kwargs) -> Any:
        identity = self.get_authenticator().authenticate(request, **kwargs)
        if identity is None:
            raise AuthenticationFailed("Invalid MCP REST credentials.")
        if isinstance(identity, SBAdminMCPRestIdentity):
            return identity.user
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
        except PermissionDenied:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        except (Http404, LookupError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class SBAdminMCPToolsManifestAPIView(SBAdminMCPToolAPIView):
    """REST equivalent of MCP ``tools/list`` for guarded SBAdmin tools."""

    def get(self, request: Request, **kwargs) -> Response:
        try:
            request.user = self.authenticate_rest_request(request, **kwargs)
            result = list_sbadmin_mcp_tools(
                request=request, toolset_cls=self.toolset_cls
            )
        except AuthenticationFailed:
            return Response(
                {"detail": "Invalid MCP REST credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except PermissionDenied:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        return Response(result)


class SBAdminMCPRestCapabilitiesAPIView(SBAdminMCPToolAPIView):
    """REST metadata roughly equivalent to MCP ``initialize`` output."""

    def get(self, request: Request, **kwargs) -> Response:
        try:
            request.user = self.authenticate_rest_request(request, **kwargs)
        except AuthenticationFailed:
            return Response(
                {"detail": "Invalid MCP REST credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except PermissionDenied:
            return Response(
                {"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN
            )
        return Response(get_sbadmin_mcp_rest_capabilities(toolset_cls=self.toolset_cls))
