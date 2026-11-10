"""Safe local failure descriptions, retained across SDK transport tasks."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum


class MCPFailure(StrEnum):
    AUTH_REJECTED = "AUTH"
    TOOL_COUNT = "MCP_TOOL_COUNT_LIMIT"
    CATALOG_SIZE = "MCP_CATALOG_SIZE_LIMIT"
    RESPONSE_SIZE = "MCP_RESPONSE_SIZE_LIMIT"
    RESULT_SIZE = "MCP_RESULT_SIZE_LIMIT"
    DISCOVERY_TIMEOUT = "MCP_DISCOVERY_TIMEOUT"
    TOOL_TIMEOUT = "MCP_TOOL_TIMEOUT"
    NETWORK_TIMEOUT = "MCP_NETWORK_TIMEOUT"


_MESSAGES = {
    MCPFailure.AUTH_REJECTED: "The MCP server rejected the access token.",
    MCPFailure.TOOL_COUNT: "This server offers more than omnideck's limit of 500 tools. Ask the service to expose a smaller tool catalog.",
    MCPFailure.CATALOG_SIZE: "This server's tool catalog is too large for omnideck (1 MiB limit). Ask the service to reduce its tool descriptions or schemas.",
    MCPFailure.RESPONSE_SIZE: "The MCP server response exceeded omnideck's 4 MiB limit. Request less data or ask the service to return smaller responses.",
    MCPFailure.RESULT_SIZE: "The tool result exceeded omnideck's 2 MiB limit. Narrow the request or ask for fewer results.",
    MCPFailure.DISCOVERY_TIMEOUT: "The server took too long to list its tools (30-second limit). Try connecting again when the service is responding.",
    MCPFailure.TOOL_TIMEOUT: "The remote tool did not return a result within omnideck's 60-second limit.",
    MCPFailure.NETWORK_TIMEOUT: "The MCP server did not respond before the network timeout.",
}

# The SDK can replace a transport exception with a generic connection error.
# It propagates the sending request's context to transport tasks. Retain only
# our local failure code in that request's shared cell, never upstream text.
_FAILURES: ContextVar[list[MCPFailure] | None] = ContextVar("mcp_request_failures", default=None)


class MCPRequestError(ValueError):
    def __init__(self, reason: MCPFailure) -> None:
        self.code = reason.value
        self.message = _MESSAGES[reason]
        super().__init__(self.message)


def request_failure(reason: MCPFailure) -> MCPRequestError:
    failures = _FAILURES.get()
    if failures is not None and not failures:
        failures.append(reason)
    return MCPRequestError(reason)


@contextmanager
def mcp_error_boundary() -> Iterator[None]:
    failures: list[MCPFailure] = []
    parent = _FAILURES.get()
    token = _FAILURES.set(failures)
    try:
        try:
            yield
        except Exception as exc:
            if failures:
                raise MCPRequestError(failures[0]) from exc
            raise
        if failures:
            raise MCPRequestError(failures[0])
    finally:
        _FAILURES.reset(token)
        # Discovery runs inside setup's SDK context. Its teardown may wrap
        # the error in an ExceptionGroup; keep the local reason for setup too.
        if failures and parent is not None and not parent:
            parent.append(failures[0])
