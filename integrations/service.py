"""Supported application API for discovering and invoking integrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from config import load_config
from integrations import broker_client, supervisor_client
from integrations.broker_client import IntegrationError, IntegrationPermissionDenied
from integrations.operations import operation_for_id
from integrations.supervisor_client import SupervisorError


@dataclass(frozen=True)
class InvocationContext:
    """Identity of the consumer using an integration operation."""

    consumer: Literal["agent", "custom_app"]
    consumer_id: str | None = None


AGENT_CONTEXT = InvocationContext(consumer="agent")


class IntegrationService:
    """Structured integration boundary shared by agent and future SDK adapters."""

    async def list_instances(
        self,
        context: InvocationContext,
        *,
        app_sock_path: Path | str | None = None,
    ) -> list[dict[str, Any]]:
        """List non-secret integration instances visible to ``context``."""
        self._require_supported_context(context)
        try:
            result = await supervisor_client.call(
                "list",
                {"kind": "integration"},
                app_sock_path=app_sock_path or _app_sock_path(),
            )
        except SupervisorError as exc:
            raise IntegrationError(f"could not list integrations: {exc.message}") from exc
        return list(result.get("connections") or result.get("integrations") or [])

    async def list_operations(
        self,
        context: InvocationContext,
        instance_id: str,
        *,
        app_sock_path: Path | str | None = None,
    ) -> list[dict[str, Any]]:
        """List available operations and grant state for one instance."""
        self._require_supported_context(context)
        try:
            result = await supervisor_client.call(
                "resolve",
                {"id": instance_id},
                app_sock_path=app_sock_path or _app_sock_path(),
            )
        except SupervisorError as exc:
            raise IntegrationError(f"could not inspect {instance_id!r}: {exc.message}") from exc
        if result.get("kind") != "integration":
            raise IntegrationError(f"{instance_id!r} is not a tool integration")
        granted = frozenset(result.get("operation_grants") or ())
        return [
            {**descriptor, "granted": descriptor.get("id") in granted}
            for descriptor in result.get("operations") or ()
            if isinstance(descriptor, dict)
        ]

    async def invoke(
        self,
        context: InvocationContext,
        instance_id: str,
        operation_id: str,
        arguments: dict[str, Any],
        *,
        app_sock_path: Path | str | None = None,
    ) -> Any:
        """Invoke one canonical operation and return its structured result."""
        self._require_supported_context(context)
        if operation_for_id(operation_id) is None:
            raise IntegrationError(f"unknown integration operation: {operation_id}")
        if not isinstance(arguments, dict):
            raise IntegrationError("integration operation arguments must be an object")
        return await broker_client.call(
            instance_id,
            operation_id,
            arguments,
            app_sock_path=app_sock_path or _app_sock_path(),
        )

    @staticmethod
    def _require_supported_context(context: InvocationContext) -> None:
        if context.consumer != "agent":
            raise IntegrationPermissionDenied(
                "Custom App operation grants are not implemented; access is denied by default.",
            )


def _app_sock_path() -> Path:
    return Path(load_config().integrations.app_sock_path)


integration_service = IntegrationService()

__all__ = [
    "AGENT_CONTEXT",
    "IntegrationService",
    "InvocationContext",
    "integration_service",
]
