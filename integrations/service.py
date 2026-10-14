"""Supported application API for discovering and invoking integrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import load_config
from brokering import broker_client, supervisor_client
from brokering.broker_client import IntegrationError
from integrations.operations import operation_for_id
from brokering.supervisor_client import SupervisorError


class IntegrationService:
    """Structured discovery and invocation with broker-enforced connection grants."""

    async def list_connections(
        self,
        *,
        app_sock_path: Path | str | None = None,
    ) -> list[dict[str, Any]]:
        """List non-secret connections, including available operations and grants."""
        try:
            result = await supervisor_client.call(
                "list",
                {"kind": "integration"},
                app_sock_path=app_sock_path or _app_sock_path(),
            )
        except SupervisorError as exc:
            raise IntegrationError(f"could not list integrations: {exc.message}") from exc
        except OSError as exc:
            raise IntegrationError(f"could not list integrations: {exc}") from exc
        # Keep wire-format validation here; consumers receive connections, not
        # supervisor envelopes. Do not coerce malformed containers with list().
        if not isinstance(result, dict):
            raise IntegrationError("integration list response must be an object")
        connections = result.get("connections")
        if not isinstance(connections, list) or any(not isinstance(item, dict) for item in connections):
            raise IntegrationError("integration list response must contain an array of objects")
        return list(connections)

    async def invoke(
        self,
        connection_id: str,
        operation_id: str,
        arguments: dict[str, Any],
        *,
        app_sock_path: Path | str | None = None,
    ) -> Any:
        """Invoke one canonical operation and return its structured result."""
        if operation_for_id(operation_id) is None:
            raise IntegrationError(f"unknown integration operation: {operation_id}")
        if not isinstance(arguments, dict):
            raise IntegrationError("integration operation arguments must be an object")
        try:
            return await broker_client.call(
                connection_id,
                operation_id,
                arguments,
                app_sock_path=app_sock_path or _app_sock_path(),
            )
        except OSError as exc:
            # The client maps broker errors, but socket I/O can still fail
            # after connecting. Keep transport failures behind this boundary.
            raise IntegrationError(f"could not invoke {operation_id!r} on {connection_id!r}: {exc}") from exc


def _app_sock_path() -> Path:
    return Path(load_config().integrations.app_sock_path)


integration_service = IntegrationService()

__all__ = [
    "IntegrationService",
    "integration_service",
]
