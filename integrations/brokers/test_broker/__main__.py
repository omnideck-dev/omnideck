"""Entry point for the explicitly enabled deterministic test broker."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from integrations._env import env_required
from integrations._perms import PROCESS_UMASK, disable_core_dumps
from integrations._rpc import serve_rpc
from integrations.brokers._common._exit_codes import AUTH_FAIL, CLEAN_SHUTDOWN
from integrations.brokers._common._ready import print_ready
from integrations.brokers.test_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

logger = logging.getLogger("test_broker")

os.umask(PROCESS_UMASK)
disable_core_dumps()


async def _run() -> int:
    integration_id = env_required("INTEGRATION_ID")
    socket_path = Path(env_required("BROKER_SOCKET"))
    token = env_required("TEST_TOKEN")
    expected_token = env_required("TEST_EXPECTED_TOKEN")
    initial_value = env_required("TEST_INITIAL_VALUE")
    operation_grants = operation_grants_from_env(env_required("OPERATION_GRANTS"))
    os.environ.pop("TEST_TOKEN", None)

    log = logging.getLogger(f"test_broker[{integration_id}]")
    if token != expected_token:
        log.error("test credential rejected")
        return AUTH_FAIL

    dispatcher = VerbDispatcher(
        operation_grants=operation_grants,
        initial_value=initial_value,
    )

    async def handler(verb: str, args: dict[str, Any]) -> dict[str, Any]:
        return await dispatcher.dispatch(verb, args)

    server = await serve_rpc(socket_path, handler)
    log.info("listening on %s (operation_grants=%s)", socket_path, sorted(operation_grants))
    print_ready()
    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            log.info("shutting down")
    return CLEAN_SHUTDOWN


def main() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[%(name)s] %(asctime)s %(levelname)s %(message)s",
    )
    try:
        code = asyncio.run(_run())
    except KeyboardInterrupt:
        code = CLEAN_SHUTDOWN
    sys.exit(code)


if __name__ == "__main__":
    main()
