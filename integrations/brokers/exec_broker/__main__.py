"""CLI-exec broker entry point: ``python -m integrations.brokers.exec_broker``.

The supervisor spawns this with the fixed target binary, its secret(s), and
(optionally) a folder scope in the environment. The broker execs that binary
per ``run_command`` RPC call — never a shell — with the caller supplying only
trailing arguments. There is no startup credential validation — a bad token
surfaces on the first agent call as whatever exit code/stderr the target
binary produces for a rejected credential.

Exit codes:

- 0: clean shutdown.
- 1: env-parse failure or internal error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from integrations._env import env_required
from integrations._perms import PROCESS_UMASK, disable_core_dumps
from integrations._rpc import serve_rpc
from integrations.brokers._common._exit_codes import CLEAN_SHUTDOWN, GENERIC_ERROR
from integrations.brokers._common._ready import print_ready
from integrations.brokers.exec_broker._verbs import VerbDispatcher
from integrations.permissions import permissions_from_env

logger = logging.getLogger("exec_broker")

os.umask(PROCESS_UMASK)
disable_core_dumps()


def _parse_json_str_list(env_var: str, raw: str) -> list[str] | None:
    """Parse ``raw`` as a JSON list of strings, or log and return ``None`` on failure."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("malformed %s: %r", env_var, raw)
        return None
    if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
        logger.error("%s must be a JSON list of strings: %r", env_var, raw)
        return None
    return value


async def _run() -> int:
    integration_id = env_required("INTEGRATION_ID")
    socket_path = Path(env_required("BROKER_SOCKET"))
    cli_bin = env_required("CLI_BIN")
    workspace_root = Path(env_required("HOME_DIR"))
    permissions = permissions_from_env(env_required("PERMISSIONS"))
    path_prefix = os.environ.get("PATH_PREFIX", "")

    cli_bin_args = _parse_json_str_list("CLI_BIN_ARGS", os.environ.get("CLI_BIN_ARGS", "[]"))
    if cli_bin_args is None:
        return GENERIC_ERROR

    secret_env_keys = _parse_json_str_list("SECRET_ENV_KEYS", os.environ.get("SECRET_ENV_KEYS", "[]"))
    if secret_env_keys is None:
        return GENERIC_ERROR
    secret_values = [os.environ[k] for k in secret_env_keys if k in os.environ]

    # The child process needs the secrets in its own env (that's the whole
    # point), so we don't pop them from os.environ here the way http_broker
    # does with TOKEN — this process's env IS the child's env via inherit.
    # Redaction of anything that leaks into stdout/stderr happens per-call
    # in the verb dispatcher instead.

    log = logging.getLogger(f"exec_broker[{integration_id}]")

    dispatcher = VerbDispatcher(
        cli_bin=cli_bin,
        cli_bin_args=cli_bin_args,
        env=dict(os.environ),
        secret_values=secret_values,
        workspace_root=workspace_root,
        path_prefix=path_prefix,
        permissions=permissions,
    )

    async def handler(verb: str, args: dict[str, Any]) -> dict[str, Any]:
        return await dispatcher.dispatch(verb, args)

    server = await serve_rpc(socket_path, handler)
    log.info(
        "listening on %s (cli_bin=%s, path_prefix=%r, permissions=%s)",
        socket_path, cli_bin, path_prefix, permissions,
    )
    print_ready()

    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            log.info("shutting down")

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
