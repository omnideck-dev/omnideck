"""Google Workspace broker: refresh candidate credentials before activating them."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from brokering._control import CredentialRejected
from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from brokering.brokers.google_workspace_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

os.umask(PROCESS_UMASK)
disable_core_dumps()

_OAUTH_ENV_VARS = (
    "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_ACCESS_TOKEN",
    "OAUTH_REFRESH_TOKEN", "OAUTH_TOKEN_URI", "OAUTH_SCOPES", "OAUTH_EXPIRES_AT",
)


@asynccontextmanager
async def create_session(connection_fields: dict[str, str], downloads_dir: Path) -> AsyncIterator[VerbDispatcher]:
    """Create a Google session: dispatcher backed by refreshed OAuth credentials.

    Refresh validates the token, not access to every API/scope. Unlike email,
    this session has no persistent transport; services are built per request.
    """
    expires = int(connection_fields["OAUTH_EXPIRES_AT"])
    creds = Credentials(
        token=connection_fields["OAUTH_ACCESS_TOKEN"], refresh_token=connection_fields["OAUTH_REFRESH_TOKEN"],
        token_uri=connection_fields["OAUTH_TOKEN_URI"], client_id=connection_fields["OAUTH_CLIENT_ID"],
        client_secret=connection_fields["OAUTH_CLIENT_SECRET"], scopes=connection_fields["OAUTH_SCOPES"].split(),
        expiry=datetime.fromtimestamp(expires, tz=UTC).replace(tzinfo=None) if expires else None,
    )
    try:
        await asyncio.to_thread(creds.refresh, Request())
    except RefreshError as exc:
        raise CredentialRejected("AUTH") from exc
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
    """Run the broker; startup rejection uses the supervisor's auth exit code."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format=f"[google_workspace_broker[{env_required('INTEGRATION_ID')}]] %(asctime)s %(levelname)s %(message)s",
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
