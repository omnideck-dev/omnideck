"""Spawn the broker subprocess for one integration; wait for READY sentinel.

Called by the supervisor's ``add`` path. Produces a :class:`BrokerHandle` the
registry stores until the integration is removed. If the broker exits before
printing ``READY\\n``, we surface the exit code so the caller can distinguish
auth-fail (``77``) from a generic failure (``1``) and respond accordingly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from integrations.permissions import Permissions, permissions_to_env
from integrations.supervisor._catalog import CatalogEntry
from integrations.supervisor.types import HostPath

logger = logging.getLogger(__name__)

_READY_TIMEOUT_SECONDS = 30.0

# Env var names a dynamic-spawn secret bundle may not define — spawn-critical
# vars the supervisor sets itself, plus the CLI_BIN* pair the dynamic-spawn
# path also owns. A bundle field colliding with one of these would silently
# override supervisor-controlled wiring rather than just adding a new var.
_DYNAMIC_ENV_RESERVED = frozenset({
    "PATH", "HOME", "USER", "SHELL", "LANG", "TERM",
    "INTEGRATION_ID", "BROKER_SOCKET", "PERMISSIONS", "PATH_PREFIX",
    "CLI_BIN", "CLI_BIN_ARGS",
})
_DYNAMIC_ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


class BrokerSpawnError(Exception):
    """Broker subprocess failed to reach READY — early exit, timeout, or env problem.

    ``exit_code`` is populated when we observed a definite exit code (so the caller
    can distinguish ``77`` / auth failure from ``1`` / network failure). It's
    ``None`` when the broker hit the READY-timeout and we had to SIGKILL it.
    """

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class BrokerHandle:
    """The running broker subprocess for one integration."""

    integration_id: str
    socket_path: Path
    proc: asyncio.subprocess.Process


async def spawn_broker(
    *,
    entry: CatalogEntry,
    integration_id: str,
    secret_bundle: dict,
    permissions: Permissions,
    sockets_dir: Path,
    host_paths: dict[str, HostPath],
) -> BrokerHandle:
    """Spawn the broker for ``integration_id`` from its catalog entry.

    Combines the entry's static env, the credential-to-env mapping, the
    per-spawn ``INTEGRATION_ID`` / ``BROKER_SOCKET`` / ``PERMISSIONS`` vars,
    and any host-path bindings the entry declares (each role looked up in
    ``host_paths`` and injected as the binding's env_var). Awaits ``READY\\n``
    on the subprocess's stdout before returning.
    """
    sockets_dir.mkdir(parents=True, exist_ok=True)
    socket_path = sockets_dir / f"{integration_id}.sock"

    # Start from the supervisor's own env so the child inherits PATH, VIRTUAL_ENV,
    # and whatever else Python needs to resolve. Our explicit overrides win on
    # conflict. When we harden the container, swap to a curated allow-list.
    env: dict[str, str] = dict(os.environ)
    env.update(entry.static_env)
    secret_env_names: list[str] = []
    for blob_key, env_name in entry.env_injection.items():
        if blob_key not in secret_bundle:
            msg = f"env_injection references missing auth field: {blob_key!r}"
            raise BrokerSpawnError(msg)
        env[env_name] = secret_bundle[blob_key]
        secret_env_names.append(env_name)
    if entry.injects_path_prefix:
        env["PATH_PREFIX"] = str(secret_bundle.get("path_prefix") or "")
    if entry.dynamic_spawn:
        # Reserve every name this spawn will also set outside the bundle —
        # the static list plus whatever this specific entry's static_env /
        # env_injection / host_paths bindings contribute (e.g. HOME_DIR for
        # CLI-exec entries). A name reserved only in the static list would
        # miss entry-specific env vars set later in this function, letting a
        # bundle var quietly get overwritten by real (non-secret) wiring
        # while its name stays in SECRET_ENV_KEYS.
        reserved = (
            _DYNAMIC_ENV_RESERVED
            | set(entry.static_env)
            | set(entry.env_injection.values())
            | {binding.env_var for binding in entry.host_paths}
        )
        secret_env_names.extend(_apply_dynamic_spawn(env, secret_bundle, reserved=reserved))
    if entry.redact_secret_env:
        env["SECRET_ENV_KEYS"] = json.dumps(secret_env_names)
    for binding in entry.host_paths:
        spec = host_paths.get(binding.role)
        if spec is None:
            # Catalog references a role the supervisor doesn't know about.
            # Startup validation should have caught this; the defensive check
            # here keeps a misconfigured spawn from racing past.
            msg = f"host_paths references unknown role: {binding.role!r}"
            raise BrokerSpawnError(msg)
        env[binding.env_var] = str(spec.path)
    env["INTEGRATION_ID"] = integration_id
    env["BROKER_SOCKET"] = str(socket_path)
    env["PERMISSIONS"] = permissions_to_env(permissions)

    logger.info("spawning broker for %s at %s", integration_id, socket_path)

    # stderr inherits the supervisor's fd — broker logs land directly in the
    # host's stderr (docker logs, journald, etc.) without a forwarding hop.
    # The broker's own log format already prefixes ``[email_broker[<id>]]``
    # so per-integration filtering still works.
    proc = await asyncio.create_subprocess_exec(
        *entry.command,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
    )

    try:
        await asyncio.wait_for(_wait_for_ready(proc), timeout=_READY_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        # Broker hung during its handshake — SIGKILL + reap so we don't orphan.
        proc.kill()
        await proc.wait()
        msg = f"broker did not print READY within {_READY_TIMEOUT_SECONDS}s"
        raise BrokerSpawnError(msg, exit_code=None) from exc

    return BrokerHandle(
        integration_id=integration_id,
        socket_path=socket_path,
        proc=proc,
    )


def _apply_dynamic_spawn(
    env: dict[str, str],
    secret_bundle: dict,
    *,
    reserved: frozenset[str] = _DYNAMIC_ENV_RESERVED,
) -> list[str]:
    """Fill in ``CLI_BIN``/``CLI_BIN_ARGS`` and named vars from the bundle itself.

    Used by catalog entries where the target binary and secret var names are
    user-defined at add-time rather than fixed in the catalog (e.g. a custom
    CLI/script integration). Every var name is validated against ``reserved``
    and a strict ``[A-Z_][A-Z0-9_]*`` pattern so a bundle can't clobber
    spawn-critical env vars or smuggle in something the shell would treat
    specially. ``reserved`` defaults to the spawn-generic names but callers
    should pass the entry-specific superset (its own static_env/env_injection/
    host_paths names too) so a bundle var can't collide with wiring this
    particular catalog entry adds after this function returns. Returns the
    injected var names, so the caller can fold them into ``SECRET_ENV_KEYS``.
    """
    command = secret_bundle.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        msg = "dynamic_spawn requires a non-empty 'command' list of strings in the secret bundle"
        raise BrokerSpawnError(msg)
    env["CLI_BIN"] = command[0]
    env["CLI_BIN_ARGS"] = json.dumps(command[1:])

    variables = secret_bundle.get("vars") or {}
    if not isinstance(variables, dict):
        msg = "dynamic_spawn 'vars' must be a dict"
        raise BrokerSpawnError(msg)
    injected_names: list[str] = []
    for name, value in variables.items():
        if not isinstance(name, str) or not _DYNAMIC_ENV_NAME_PATTERN.match(name):
            msg = f"invalid env var name in secret bundle: {name!r}"
            raise BrokerSpawnError(msg)
        if name in reserved:
            msg = f"env var name is reserved: {name!r}"
            raise BrokerSpawnError(msg)
        if not isinstance(value, str):
            msg = f"env var {name!r} value must be a string"
            raise BrokerSpawnError(msg)
        env[name] = value
        injected_names.append(name)
    return injected_names


async def _wait_for_ready(proc: asyncio.subprocess.Process) -> None:
    """Read broker stdout until the ``READY`` line — or raise if it exits first."""
    # ``proc.stdout`` is typed ``StreamReader | None`` because asyncio only wires
    # it when the subprocess was spawned with ``stdout=PIPE``. We always are
    # above, but the type checker can't see that. Capture to a local so the
    # loop below sees a plain ``StreamReader`` without a runtime assert.
    stdout = proc.stdout
    if stdout is None:
        msg = "broker subprocess was spawned without a stdout pipe"
        raise BrokerSpawnError(msg)
    while True:
        line = await stdout.readline()
        if not line:
            # EOF on stdout: broker exited without emitting READY. wait() gives us
            # the definite exit code.
            code = await proc.wait()
            msg = f"broker exited with code {code} before READY"
            raise BrokerSpawnError(msg, exit_code=code)
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if text == "READY":
            return
        # Any pre-READY chatter (shouldn't happen under our broker's contract but
        # costs little to log) ends up in the supervisor's own logs.
        logger.info("broker stdout pre-READY: %s", text)
