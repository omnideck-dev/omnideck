"""Shared MCP protocol API for setup, supervisor refresh and broker execution.

This package owns protected HTTP transport, SDK OAuth state adaptation, tool
catalog discovery and safe protocol errors. Callers own browser interaction,
credential persistence, connection lifetime and tool permissions. It never
imports the app server, supervisor, or broker implementations.
"""

from ._client import connect, discover
from ._errors import MCPFailure, MCPRequestError, mcp_error_boundary, request_failure
from ._network import mcp_http_client, validated_address
from ._oauth import OAuthStorage, PersistentOAuthProvider

__all__ = [
    "MCPFailure", "MCPRequestError", "OAuthStorage", "PersistentOAuthProvider",
    "connect", "discover", "mcp_error_boundary", "mcp_http_client",
    "request_failure", "validated_address",
]
