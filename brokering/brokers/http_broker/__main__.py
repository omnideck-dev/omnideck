"""HTTP broker: replace configuration locally without claiming upstream validation."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from brokering._control import CredentialRejected
from brokering._env import capture_connection_fields, env_required
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from brokering.brokers.http_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

os.umask(PROCESS_UMASK)
disable_core_dumps()


@asynccontextmanager
async def create_session(connection_fields: dict[str, str], downloads_dir: Path) -> AsyncIterator[VerbDispatcher]:
    """Create an HTTP broker session: dispatcher, request settings, and HTTP client.

    Validate local configuration only; generic APIs have no common auth probe.
    The aiohttp client is a resource within this broker session, not the session
    abstraction itself. Exiting the factory closes its connection pool.
    """
    base = urlsplit(connection_fields["BASE_URL"])
    header = connection_fields.get("AUTH_HEADER_NAME") or "Authorization"
    template = connection_fields.get("AUTH_HEADER_TEMPLATE") or "Bearer {token}"
    value = template.format(token=connection_fields["TOKEN"])
    if base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password:
        raise ValueError("invalid base URL")
    if not header or any(c.isspace() or c in ":\r\n" for c in header) or "\r" in value or "\n" in value:
        raise ValueError("invalid authentication header")
    async with aiohttp.ClientSession() as http_client:
        yield VerbDispatcher(
            session=http_client, base_url=connection_fields["BASE_URL"], header_name=header,
            header_template=template, token=connection_fields["TOKEN"],
            operation_grants=frozenset(), downloads_dir=downloads_dir,
        )


async def _run() -> None:
    socket_path = Path(env_required("BROKER_SOCKET"))
    grants = operation_grants_from_env(env_required("OPERATION_GRANTS"))
    downloads_dir = Path(env_required("DOWNLOADS_DIR"))
    connection_fields = capture_connection_fields(("BASE_URL", "TOKEN"), ("AUTH_HEADER_NAME", "AUTH_HEADER_TEMPLATE"))
    await run_integration_broker(
        socket_path, connection_fields, grants,
        lambda candidate_fields: create_session(candidate_fields, downloads_dir),
    )

def main() -> None:
    """Run the broker; startup rejection uses the supervisor's auth exit code."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format=f"[http_broker[{env_required('INTEGRATION_ID')}]] %(asctime)s %(levelname)s %(message)s",
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
