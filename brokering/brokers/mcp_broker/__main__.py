"""One isolated MCP broker process per configured integration."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from integrations.operation_grants import operation_grants_from_env
from .client import MCPDispatcher, connect, discover
from integrations.catalog import test_integrations_enabled


@asynccontextmanager
async def create_session(fields: dict[str, str]) -> AsyncIterator[MCPDispatcher]:
    async with connect(
        fields["MCP_ENDPOINT"], token=fields["MCP_ACCESS_TOKEN"],
        allow_loopback=test_integrations_enabled(),
    ) as client:
        yield MCPDispatcher(client, await discover(client))


async def _run() -> None:
    fields = capture_connection_fields(("MCP_ENDPOINT", "MCP_ACCESS_TOKEN"))
    await run_integration_broker(
        Path(env_required("BROKER_SOCKET")), fields,
        operation_grants_from_env(env_required("OPERATION_GRANTS")), create_session,
    )


if __name__ == "__main__":
    os.umask(PROCESS_UMASK)
    disable_core_dumps()
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception:
        sys.exit(1)
