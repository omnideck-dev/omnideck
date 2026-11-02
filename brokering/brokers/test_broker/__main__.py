"""Deterministic development broker with real control-channel credential updates."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from brokering._control import CredentialRejected
from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from brokering.brokers.test_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

os.umask(PROCESS_UMASK)
disable_core_dumps()


async def _run() -> None:
    socket_path = Path(env_required("BROKER_SOCKET"))
    grants = operation_grants_from_env(env_required("OPERATION_GRANTS"))
    connection_fields = capture_connection_fields(("TEST_TOKEN", "TEST_EXPECTED_TOKEN", "TEST_INITIAL_VALUE"))
    dispatcher = VerbDispatcher(operation_grants=grants, initial_value=connection_fields["TEST_INITIAL_VALUE"])

    @asynccontextmanager
    async def create_session(connection_fields: dict[str, str]) -> AsyncIterator[VerbDispatcher]:
        """Validate test credentials and reuse the simulated upstream dispatcher."""
        if connection_fields["TEST_TOKEN"] != connection_fields["TEST_EXPECTED_TOKEN"]:
            raise CredentialRejected("AUTH")
        # Credential updates should not erase the fixture's simulated upstream state.
        yield dispatcher

    await run_integration_broker(socket_path, connection_fields, grants, create_session)

def main() -> None:
    """Run the broker; startup rejection uses the supervisor's auth exit code."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format=f"[test_broker[{env_required('INTEGRATION_ID')}]] %(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except CredentialRejected as exc:
        sys.exit(77 if exc.code == "AUTH" else 1)
    except Exception as exc:
        # Upstream exceptions can contain tokens or passwords.
        logging.error("broker failed during startup or control handling (%s)", type(exc).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
