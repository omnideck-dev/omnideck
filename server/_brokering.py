"""Server-side connection-management client shared by route families."""

import asyncio
from typing import Any

from brokering import supervisor_client
from config import load_config


async def supervisor_call(verb: str, args: dict[str, Any]) -> dict[str, Any]:
    """Bound a supervisor call, including credential handoff and cleanup.

    Startup and each credential control exchange may take 30 seconds. Ninety
    seconds leaves room for prepare, activate/discard, and cleanup. Route handlers map
    ``TimeoutError`` (an ``OSError``) to service-unavailable responses.
    """
    # Keep the persisted configuration key stable across the package split.
    app_sock = load_config().integrations.app_sock_path
    return await asyncio.wait_for(
        supervisor_client.call(verb, args, app_sock_path=app_sock),
        timeout=90.0,
    )
