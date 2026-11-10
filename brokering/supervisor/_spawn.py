"""Spawn the broker subprocess for one integration; wait for READY sentinel.

Called by the supervisor's startup, add, and recovery paths. Produces a :class:`BrokerHandle` the
registry stores until the integration is removed. If the broker exits before
printing ``READY\\n``, we surface the exit code so the caller can distinguish
auth-fail (``77``) from a generic failure (``1``) and respond accordingly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from brokering.catalog import CatalogEntry
from brokering.connection_data import BrokerConnectionData
from integrations.operation_grants import OperationGrants, operation_grants_to_env
from brokering.supervisor.types import HostPath

logger = logging.getLogger(__name__)

_READY_TIMEOUT_SECONDS = 30.0


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

    connection_id: str
    socket_path: Path
    proc: asyncio.subprocess.Process


def connection_fields(entry: CatalogEntry, secret_bundle: BrokerConnectionData) -> dict[str, str]:
    """Bind connection data consistently for startup and private live updates."""
    fields = dict(entry.driver_config)
    for blob_key, env_name in entry.driver.env_injection.items():
        if blob_key not in secret_bundle:
            raise BrokerSpawnError(f"env_injection references missing auth field: {blob_key!r}")
        value = secret_bundle[blob_key]
        if not isinstance(value, str):
            raise BrokerSpawnError(f"auth field {blob_key!r} must be a string")
        fields[env_name] = value
    return fields


async def spawn_broker(
    *,
    entry: CatalogEntry,
    connection_id: str,
    secret_bundle: BrokerConnectionData,
    operation_grants: OperationGrants,
    sockets_dir: Path,
    host_paths: dict[str, HostPath],
) -> BrokerHandle:
    """Spawn the broker for ``connection_id`` from its catalog entry.

    Combines the entry's driver config, credential bindings, the per-spawn
    ``INTEGRATION_ID`` / ``BROKER_SOCKET`` / ``OPERATION_GRANTS`` vars,
    and any host-path bindings the entry declares (each role looked up in
    ``host_paths`` and injected as the binding's env_var). Awaits ``READY\\n``
    on the subprocess's stdout before returning.
    """
    sockets_dir.mkdir(parents=True, exist_ok=True)
    socket_path = sockets_dir / f"{connection_id}.sock"

    # Start from the supervisor's own env so the child inherits PATH, VIRTUAL_ENV,
    # and whatever else Python needs to resolve. Our explicit overrides win on
    # conflict. When we harden the container, swap to a curated allow-list.
    env: dict[str, str] = dict(os.environ)
    env.update(connection_fields(entry, secret_bundle))
    for binding in entry.driver.host_paths:
        spec = host_paths.get(binding.role)
        if spec is None:
            # Catalog references a role the supervisor doesn't know about.
            # Startup validation should have caught this; the defensive check
            # here keeps a misconfigured spawn from racing past.
            msg = f"host_paths references unknown role: {binding.role!r}"
            raise BrokerSpawnError(msg)
        env[binding.env_var] = str(spec.path)
    env["INTEGRATION_ID"] = connection_id
    env["BROKER_SOCKET"] = str(socket_path)
    env["OPERATION_GRANTS"] = operation_grants_to_env(operation_grants)

    logger.info("spawning broker for %s at %s", connection_id, socket_path)

    # stderr inherits the supervisor's fd — broker logs land directly in the
    # host's stderr (docker logs, journald, etc.) without a forwarding hop.
    # The broker's own log format already prefixes ``[email_broker[<id>]]``
    # so per-integration filtering still works.
    try:
        proc = await asyncio.create_subprocess_exec(
            *entry.driver.command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
    except (OSError, TypeError) as exc:
        raise BrokerSpawnError(f"could not start broker process: {exc}") from exc

    try:
        await asyncio.wait_for(_wait_for_ready(proc), timeout=_READY_TIMEOUT_SECONDS)
    except (Exception, asyncio.CancelledError) as exc:
        # Until READY, this function owns the child. Failure or cancellation
        # must reap it because the registry has no handle to clean up yet.
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass  # The child exited between checking and signalling.
        await proc.wait()
        if isinstance(exc, TimeoutError):
            msg = f"broker did not print READY within {_READY_TIMEOUT_SECONDS}s"
            raise BrokerSpawnError(msg, exit_code=None) from exc
        raise

    return BrokerHandle(
        connection_id=connection_id,
        socket_path=socket_path,
        proc=proc,
    )


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
