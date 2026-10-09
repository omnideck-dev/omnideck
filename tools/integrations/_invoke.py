"""Thin agent-adapter bridge to the structured integration service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from integrations.service import integration_service


async def invoke_operation(
    connection_id: str,
    operation_id: str,
    arguments: dict[str, Any],
    *,
    app_sock_path: Path | str,
) -> Any:
    """Invoke through the application service instead of exposing broker verbs."""
    return await integration_service.invoke(
        connection_id,
        operation_id,
        arguments,
        app_sock_path=app_sock_path,
    )


__all__ = ["invoke_operation"]
