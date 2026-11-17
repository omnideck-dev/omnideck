"""Google Workspace broker: use supervisor-issued access credentials only."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from google.oauth2.credentials import Credentials

from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from brokering.brokers.google_workspace_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

os.umask(PROCESS_UMASK)
disable_core_dumps()

_OAUTH_ENV_VARS = (
    "OAUTH_ACCESS_TOKEN", "OAUTH_SCOPES",
)


@asynccontextmanager
async def create_session(connection_fields: dict[str, str], downloads_dir: Path) -> AsyncIterator[VerbDispatcher]:
    """No expiry/refresh secret: the supervisor handles renewal before dispatch.

    Google-auth cannot transparently renew these credentials. A provider 401
    returns to the supervisor through the broker client without replaying the
    operation. The adapter never starts an interactive authorization flow.
    """
    creds = Credentials(
        token=connection_fields["OAUTH_ACCESS_TOKEN"], scopes=connection_fields["OAUTH_SCOPES"].split(),
    )
    # API clients build request-local services; no persistent transport to retire.
    yield VerbDispatcher(creds, operation_grants=frozenset(), downloads_dir=downloads_dir)


async def _run() -> None:
    socket_path = Path(env_required("BROKER_SOCKET"))
    grants = operation_grants_from_env(env_required("OPERATION_GRANTS"))
    downloads_dir = Path(env_required("DOWNLOADS_DIR"))
    connection_fields = capture_connection_fields(_OAUTH_ENV_VARS)
    await run_integration_broker(
        socket_path, connection_fields, grants,
        lambda candidate_fields: create_session(candidate_fields, downloads_dir),
    )

def main() -> None:
    """Run API execution; the supervisor owns authorization failures."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format=f"[google_workspace_broker[{env_required('INTEGRATION_ID')}]] %(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as exc:
        # Upstream exceptions can contain tokens or passwords.
        logging.error("broker failed during startup or control handling (%s)", type(exc).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
