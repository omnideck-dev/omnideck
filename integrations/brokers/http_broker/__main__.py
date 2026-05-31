"""HTTP broker entry point: ``python -m integrations.brokers.http_broker``.

The supervisor spawns this with the integration's base URL, auth header
config, and token in the environment. The broker holds an aiohttp session
in memory and serves a single ``http_request`` RPC over a Unix Domain
Socket. There is no startup credential validation — a bad token surfaces
on the first agent call as an upstream 401.

Exit codes:

- 0: clean shutdown.
- 1: env-parse failure or internal error.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import aiohttp

from integrations._env import env_required
from integrations._perms import PROCESS_UMASK, disable_core_dumps
from integrations._rpc import serve_rpc
from integrations.brokers._common._exit_codes import CLEAN_SHUTDOWN
from integrations.brokers._common._ready import print_ready
from integrations.brokers.http_broker._verbs import VerbDispatcher
from integrations.permissions import permissions_from_env

logger = logging.getLogger("http_broker")

os.umask(PROCESS_UMASK)
disable_core_dumps()


_DEFAULT_HEADER_NAME = "Authorization"
_DEFAULT_HEADER_TEMPLATE = "Bearer {token}"


async def _run() -> int:
    integration_id = env_required("INTEGRATION_ID")
    socket_path = Path(env_required("BROKER_SOCKET"))
    base_url = env_required("BASE_URL")
    token = env_required("TOKEN")
    header_name = os.environ.get("AUTH_HEADER_NAME") or _DEFAULT_HEADER_NAME
    header_template = (
        os.environ.get("AUTH_HEADER_TEMPLATE") or _DEFAULT_HEADER_TEMPLATE
    )
    permissions = permissions_from_env(env_required("PERMISSIONS"))
    downloads_dir = Path(env_required("DOWNLOADS_DIR"))

    # Drop the token from os.environ once we've captured it. Best-effort
    # hygiene — narrows in-process exposure (debuggers, traceback locals).
    # /proc/<pid>/environ is set at exec time and isn't updated here, but
    # it's mode 0400 and the agent runs as a different UID.
    os.environ.pop("TOKEN", None)

    log = logging.getLogger(f"http_broker[{integration_id}]")

    # One persistent session for all proxied requests — keeps the TCP pool
    # warm and avoids per-request TLS handshakes. auto_decompress lets aiohttp
    # transparently decode gzipped responses so size accounting and inline
    # decisions work on actual content bytes, not wire bytes.
    session = aiohttp.ClientSession()
    try:
        dispatcher = VerbDispatcher(
            session=session,
            base_url=base_url,
            header_name=header_name,
            header_template=header_template,
            token=token,
            permissions=permissions,
            downloads_dir=downloads_dir,
        )

        async def handler(verb: str, args: dict[str, Any]) -> dict[str, Any]:
            return await dispatcher.dispatch(verb, args)

        server = await serve_rpc(socket_path, handler)
        log.info(
            "listening on %s (base_url=%s, permissions=%s)",
            socket_path, base_url, permissions,
        )
        print_ready()

        async with server:
            try:
                await server.serve_forever()
            except asyncio.CancelledError:
                log.info("shutting down")
    finally:
        await session.close()

    return CLEAN_SHUTDOWN


def main() -> None:
    """Console entry point — configure logging, run the async body, exit with its return code."""
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
