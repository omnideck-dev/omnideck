"""One isolated MCP broker process per configured integration."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from brokering._control import CredentialRejected
from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from integrations.operation_grants import operation_grants_from_env
from .client import MCPDispatcher
from brokering.mcp_protocol import connect, discover, MCPRequestError


@asynccontextmanager
async def create_session(fields: dict[str, str]) -> AsyncIterator[MCPDispatcher]:
    try:
        async with connect(
            fields["MCP_ENDPOINT"], token=fields["MCP_ACCESS_TOKEN"],
        ) as client:
            yield MCPDispatcher(client, await discover(client))
    except MCPRequestError as exc:
        if exc.code == "AUTH":
            raise CredentialRejected("AUTH") from exc
        raise



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
    except CredentialRejected as exc:
        sys.exit(77 if exc.code == "AUTH" else 1)
    except Exception:
        sys.exit(1)
