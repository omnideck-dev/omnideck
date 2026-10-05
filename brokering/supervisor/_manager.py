"""Centralized lifecycle for broker subprocesses.

One :class:`BrokerManager` per :class:`Supervisor` instance owns *every*
spawn path:

- ``add`` — user-driven new integration (vault is fresh, secrets come
  from the request body).
- ``reconcile_existing`` — boot-time rehydrate (vault has the meta + enc;
  decrypt then spawn).
- crash respawn — automatic restart with exponential backoff after an
  unexpected broker exit.

Each running broker has a watcher task awaiting its subprocess. Two
terminal states stop the watcher's respawn loop:

- ``auth_failed`` — broker exits with code 77 (upstream rejected creds).
  Hammering the upstream's auth endpoint risks rate-limit penalties; the
  user can reconnect with replacement credentials.
- ``broken`` — three consecutive failed respawns before READY. Likely a
  config bug or dead network path. The user can retry by reconnecting.

Vault I/O, catalog lookups, and ``spawn_broker`` calls all live behind
this manager. The RPC handler (``AppSockHandler``) becomes a thin
dispatcher; the supervisor lifecycle (``Supervisor.start`` / ``stop``)
owns the manager and orchestrates startup ordering.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from brokering._rpc import RpcError
from brokering._control import CredentialRejected, credential_command, update_broker_grants
from brokering.connection_data import BrokerConnectionData
from brokering.catalog import CatalogEntry
from integrations.catalog import IntegrationCatalogEntry
from brokering.brokers.llm_proxy.catalog import ModelProviderCatalogEntry
from integrations.operation_grants import (
    OperationGrants,
    normalize_operation_grants,
)
from brokering.supervisor._crypto import DecryptError
from brokering.supervisor._registry import BrokeredConnectionRecord, Registry
from brokering.supervisor._operation_metadata import connection_operations
from brokering.supervisor._mcp_refresh import refresh_mcp_authorization
from brokering.supervisor._spawn import BrokerHandle, BrokerSpawnError, connection_fields, spawn_broker
from brokering.supervisor._store import (
    delete_connection,
    read_raw_meta,
    read_secrets,
    write_meta,
    write_secrets,
)
from brokering.supervisor.types import (
    ConnectionMeta,
    HostPath,
    IntegrationConnectionMeta,
    ModelProviderConnectionMeta,
    connection_meta_from_dict,
)

ConnectionKind = Literal["integration", "model_provider"]

logger = logging.getLogger(__name__)

# Integration IDs use [a-z0-9_-]+ up to 64 chars; enforced here so malformed
# values never reach the filesystem as partial filenames.
_SUFFIX_PATTERN = re.compile(r"^[a-z0-9_-]{1,48}$")
_SHUTDOWN_GRACE_SECONDS = 5.0

# Exponential backoff between respawn attempts: 1s, 2s, 4s, 8s, 16s, 30s cap.
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0

# How many consecutive failed respawns before giving up and marking "broken".
_MAX_CONSECUTIVE_FAILURES = 3

# Broker exit code that means "upstream rejected the credentials" — the value
# brokers' __main__ uses for ImapAuthError / similar. Hardcoded here to avoid
# importing across the broker package boundary.
_AUTH_FAIL_EXIT_CODE = 77


def _serialize_connection_mutation(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Keep one connection's control replies and lifecycle changes ordered."""
    @wraps(method)
    async def wrapped(self: BrokerManager, connection_id: str, *args: Any, **kwargs: Any) -> Any:
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {connection_id}")
        async with record.mutation_lock:
            if self._registry.get(connection_id) is not record:
                raise RpcError("NOT_FOUND", f"connection removed: {connection_id}")
            return await method(self, connection_id, *args, **kwargs)
    return wrapped


class BrokerManager:
    """Owns spawn / watch / respawn / remove for every broker."""

    def __init__(
        self,
        *,
        vault_dir: Path,
        sockets_dir: Path,
        host_paths: dict[str, HostPath],
        master_key: bytes,
        catalog: dict[str, CatalogEntry],
        registry: Registry,
    ) -> None:
        self._vault_dir = vault_dir
        self._sockets_dir = sockets_dir
        self._host_paths = host_paths
        self._master_key = master_key
        self._catalog = catalog
        self._registry = registry
        self._watchers: dict[str, asyncio.Task[None]] = {}

    # --- public lifecycle ---------------------------------------------------

    async def add(
        self,
        *,
        slug: str,
        user_suffix: str | None = None,
        label: str,
        auth_blob: BrokerConnectionData,
        operation_grants: OperationGrants | None = None,
        kind: ConnectionKind | None = None,
    ) -> BrokeredConnectionRecord:
        """Register a brand-new integration: validate, persist, spawn, watch.

        Raises :class:`RpcError` on validation failure or spawn failure;
        the handler propagates straight through.
        """
        if slug not in self._catalog:
            raise RpcError("BAD_REQUEST", f"unknown slug: {slug}")
        if user_suffix is not None and not _SUFFIX_PATTERN.match(user_suffix):
            raise RpcError(
                "BAD_REQUEST",
                "user_suffix must match [a-z0-9_-]{1,48}",
            )
        entry = self._catalog[slug]
        if kind is not None and kind != entry.kind:
            raise RpcError("BAD_REQUEST", f"catalog entry {slug!r} has kind {entry.kind!r}")
        connection_id = f"{slug}_{user_suffix}" if user_suffix else slug
        if self._registry.contains(connection_id):
            raise RpcError("BAD_REQUEST", f"integration already exists: {connection_id}")

        try:
            available_operations, discovered = connection_operations(entry, auth_blob)
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", "Invalid connection tool catalog.") from exc
        grants = _grants_for_add(
            entry,
            available_operations=available_operations,
            operation_grants=operation_grants,
        )

        now = datetime.now(UTC)
        common = {
            "id": connection_id,
            "slug": slug,
            "label": label,
            "added_at": now,
            "updated_at": now,
        }
        meta: ConnectionMeta
        if isinstance(entry, IntegrationCatalogEntry):
            meta = IntegrationConnectionMeta(**common, agent_operation_grants=grants)
        else:
            meta = ModelProviderConnectionMeta(**common)

        # Write vault first. A crash between here and the spawn leaves orphaned
        # files on disk; ``reconcile_existing`` picks them up on the next boot.
        # Better than orphaning a running broker without persisted state.
        write_meta(self._vault_dir, meta)
        write_secrets(self._vault_dir, connection_id, self._master_key, auth_blob)

        try:
            handle = await spawn_broker(
                entry=entry,
                connection_id=connection_id,
                secret_bundle=auth_blob,
                operation_grants=grants,
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            # Roll back — no broker subprocess is running at this point.
            delete_connection(self._vault_dir, connection_id)
            if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                raise RpcError("AUTH", "upstream rejected credentials") from exc
            raise RpcError("UPSTREAM", f"broker spawn failed: {exc}") from exc

        record = BrokeredConnectionRecord(
            meta=meta,
            broker=handle,
            available_operations=available_operations,
            discovered_operations=discovered,
            driver_id=entry.driver_id,
        )
        self._registry.add(record)
        self._start_watcher(connection_id)
        logger.info("added integration %s (slug=%s)", connection_id, slug)
        return record

    async def reconcile_existing(self, connection_id: str) -> BrokeredConnectionRecord:
        """Re-spawn a broker for an integration already persisted in the vault.

        Raises :class:`ReconcileError` on any failure path so the caller
        (Supervisor.start) can log and skip a single bad integration without
        bringing the whole supervisor down.
        """
        raw = read_raw_meta(self._vault_dir, connection_id)

        slug = raw.get("slug", "")
        entry = self._catalog.get(slug)
        if entry is None:
            msg = f"catalog has no entry for slug {slug!r}"
            raise ReconcileError(msg)

        try:
            secret_bundle = read_secrets(self._vault_dir, connection_id, self._master_key)
        except DecryptError as exc:
            msg = f"decrypt failed for {connection_id}: {exc}"
            raise ReconcileError(msg) from exc

        try:
            available_operations, discovered = connection_operations(entry, secret_bundle)
        except ValueError as exc:
            raise ReconcileError("Invalid saved tool catalog") from exc
        meta = connection_meta_from_dict(raw)

        expected_kind = entry.kind
        if meta.kind != expected_kind:
            raise ReconcileError(
                f"metadata kind {meta.kind!r} does not match catalog kind {expected_kind!r}",
            )

        # Scope availability informs configuration, not stored user intent.
        # Restart must pass the saved allowlist through unchanged; the upstream
        # remains responsible for authorizing the token on each API request.

        try:
            secret_bundle = await self._refresh_mcp_fields(entry, connection_id, secret_bundle)
            handle = await spawn_broker(
                entry=entry,
                connection_id=connection_id,
                secret_bundle=secret_bundle,
                operation_grants=_meta_grants(meta),
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            kind = "auth rejected" if exc.exit_code == _AUTH_FAIL_EXIT_CODE else "spawn failed"
            state: Literal["auth_failed", "broken"] = (
                "auth_failed" if exc.exit_code == _AUTH_FAIL_EXIT_CODE else "broken"
            )
            record = BrokeredConnectionRecord(
                meta=meta,
                broker=None,
                available_operations=available_operations,
                state=state,
                discovered_operations=discovered,
                driver_id=entry.driver_id,
            )
            self._registry.add(record)
            logger.warning(
                "%s for %s; retaining %s record for recovery: %s",
                kind,
                connection_id,
                state,
                exc,
            )
            return record

        record = BrokeredConnectionRecord(
            meta=meta,
            broker=handle,
            available_operations=available_operations,
            discovered_operations=discovered,
            driver_id=entry.driver_id,
        )
        self._registry.add(record)
        self._start_watcher(connection_id)
        logger.info("reconciled %s (slug=%s)", connection_id, meta.slug)
        return record

    @_serialize_connection_mutation
    async def mcp_setup_settings(self, connection_id: str) -> dict[str, str]:
        """Project a strict public allowlist from saved OAuth registration.

        Reconnect UI must not read the vault or receive serialized OAuth state,
        which also contains tokens. The existing credential transaction remains
        the sole owner of replacing this registration after successful consent.
        """
        from brokering.brokers.mcp_broker.authorization import OAuthStorage

        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", "Integration was removed.")
        if record.driver_id != "remote.mcp":
            raise RpcError("BAD_REQUEST", "This integration does not use MCP sign-in.")
        try:
            fields = read_secrets(self._vault_dir, connection_id, self._master_key)
            oauth = OAuthStorage(fields.get("oauth_state", ""))
        except Exception as exc:
            raise RpcError("AUTH", "Could not load the saved sign-in settings.") from exc
        client = oauth.client_info
        return {"endpoint": fields.get("endpoint", ""),
                "client_id": client.client_id if client else "",
                "issuer": str(client.issuer) if client and client.issuer else ""}

    @_serialize_connection_mutation
    async def ensure_fresh_authorization(self, connection_id: str) -> None:
        """Refresh MCP before resolution, serialized with edits and removal."""
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", "Integration was removed.")
        entry = self._catalog.get(record.meta.slug)
        if entry is None or entry.driver_id != "remote.mcp" or record.state != "running":
            return
        try:
            fields = read_secrets(self._vault_dir, connection_id, self._master_key)
            refreshed = await self._refresh_mcp_fields(entry, connection_id, fields)
            if refreshed is fields:
                return
            # Rotation is already authoritative on disk. Both transaction
            # recovery inputs intentionally point to the NEW credentials.
            await self._update_credentials(
                record, entry, refreshed, refreshed, record.meta, record.available_operations,
            )
        except (Exception, asyncio.CancelledError) as exc:
            record.state = "broken"
            await self._stop_record_broker(record)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RpcError("AUTH", "Could not refresh access. Sign in again to reconnect.") from exc

    async def _refresh_mcp_fields(
        self, entry: CatalogEntry, connection_id: str, fields: BrokerConnectionData,
    ) -> BrokerConnectionData:
        if entry.driver_id != "remote.mcp":
            return fields
        try:
            return await refresh_mcp_authorization(
                fields, lambda updated: write_secrets(self._vault_dir, connection_id, self._master_key, updated),
            )
        except Exception as exc:
            raise BrokerSpawnError("Could not refresh MCP access; sign in again.", exit_code=_AUTH_FAIL_EXIT_CODE) from exc

    @_serialize_connection_mutation
    async def remove(self, connection_id: str) -> None:
        """Tear down an integration: stop watcher, SIGTERM, drop registry, wipe vault.

        Raises :class:`RpcError` (NOT_FOUND) if the id isn't registered.
        """
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {connection_id}")

        # Flag the record first so the watcher sees expected_termination on
        # the next iteration (or already-pending wait), then cancel its task
        # so the SIGTERM below isn't read as a crash.
        record.expected_termination = True
        watcher = self._watchers.pop(connection_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

        self._registry.remove(connection_id)
        if record.broker is not None:
            await self._terminate_broker(record.broker)
        delete_connection(self._vault_dir, connection_id)
        logger.info("removed integration %s", connection_id)

    @_serialize_connection_mutation
    async def update(
        self,
        connection_id: str,
        *,
        operation_grants: OperationGrants | None = None,
        label: str | None = None,
    ) -> BrokeredConnectionRecord:
        """Update mutable fields on an existing integration.

        Mutables are explicit operation grants and ``label``. A label
        change is metadata-only; a grant change is persisted and acknowledged
        over the running broker's private control pipe without restarting it.

        Raises :class:`RpcError` (NOT_FOUND) if the id isn't registered.
        Failed handoffs keep the requested policy and stop the uncertain broker;
        revoked access is never restored as a recovery action.
        """
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {connection_id}")


        if operation_grants is None and label is None:
            raise RpcError("BAD_REQUEST", "update requires at least one field")

        if label is not None and not label.strip():
            raise RpcError("BAD_REQUEST", "'label' must be a non-empty string")

        requested_grants: OperationGrants | None = None
        if operation_grants is not None:
            if not isinstance(record.meta, IntegrationConnectionMeta):
                raise RpcError("BAD_REQUEST", "model providers do not have operation grants")
            requested_grants = normalize_operation_grants(
                operation_grants, record.available_operations,
            )

        grants_changed = (
            requested_grants is not None
            and isinstance(record.meta, IntegrationConnectionMeta)
            and record.meta.agent_operation_grants != requested_grants
        )
        label_changed = label is not None and record.meta.label != label

        # No-op shortcut: nothing actually different, skip the work.
        if not grants_changed and not label_changed:
            return record

        meta_updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if grants_changed:
            meta_updates["agent_operation_grants"] = requested_grants
        if label_changed:
            meta_updates["label"] = label
        new_meta = record.meta.model_copy(update=meta_updates)

        # Label-only: no env change, no respawn. Update in place and return.
        if not grants_changed:
            write_meta(self._vault_dir, new_meta)
            record.meta = new_meta
            logger.info("updated integration %s (label=%r)", connection_id, label)
            return record

        # Persist first: any crash/restart must use the requested policy. The
        # live child is acknowledged before reporting success. If either step
        # fails, stop it so old or ambiguously applied grants cannot stay live.
        try:
            write_meta(self._vault_dir, new_meta)
        except Exception as exc:
            record.state = "broken"
            await self._stop_record_broker(record)
            raise RpcError("INTERNAL", "could not persist operation grants; broker stopped") from exc
        record.meta = new_meta
        try:
            if record.broker is None or record.state != "running":
                raise ConnectionError("connection has no running broker")
            await update_broker_grants(record.broker.proc, _meta_grants(new_meta))
        except (Exception, asyncio.CancelledError) as exc:
            record.state = "broken"
            await self._stop_record_broker(record)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RpcError("UPSTREAM", "grants saved but broker update failed; reconnect required") from exc
        logger.info(
            "updated integration %s (operation_grants=%s, label=%r)",
            connection_id, sorted(_meta_grants(new_meta)), new_meta.label,
        )
        return record

    @_serialize_connection_mutation
    async def reconnect(
        self,
        connection_id: str,
        *,
        auth_blob: BrokerConnectionData,
        kind: ConnectionKind | None = None,
    ) -> BrokeredConnectionRecord:
        """Replace credentials in place, or start a broker if none is healthy.

        Tool integrations preserve exact grants independently of changes to
        remote scopes. Availability is refreshed for configuration choices;
        reconnect itself does not edit the user's allowlist. Model providers
        share credential replacement but do not carry operation grants.
        """
        record = self._registry.get(connection_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {connection_id}")
        if kind is not None and record.meta.kind != kind:
            raise RpcError(
                "BAD_REQUEST",
                f"connection {connection_id!r} has kind {record.meta.kind!r}",
            )

        entry = self._catalog.get(record.meta.slug)
        if entry is None or entry.kind != record.meta.kind:
            raise RpcError(
                "BAD_REQUEST",
                f"catalog has no {record.meta.kind!r} entry for slug {record.meta.slug!r}",
            )
        old_meta = record.meta
        try:
            new_available, _ = connection_operations(entry, auth_blob)
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", "Invalid connection tool catalog.") from exc
        new_grants = _meta_grants(old_meta)
        new_meta = old_meta.model_copy(update={"updated_at": datetime.now(UTC)})

        if record.broker is not None and record.broker.proc.returncode is None and record.state == "running":
            try:
                old_secrets = read_secrets(
                    self._vault_dir, connection_id, self._master_key,
                )
            except (DecryptError, OSError) as exc:
                raise RpcError("INTERNAL", f"decrypt failed: {exc}") from exc
            await self._update_credentials(
                record, entry, old_secrets, auth_blob, new_meta, new_available,
            )
        else:
            await self._start_reconnected_broker(
                record, entry, auth_blob, new_meta, new_available,
            )
        logger.info(
            "reconnected %s %s (operation_grants=%s)",
            record.meta.kind, connection_id, sorted(new_grants),
        )
        return record

    async def _update_credentials(
        self,
        record: BrokeredConnectionRecord,
        entry: CatalogEntry,
        old_secrets: BrokerConnectionData,
        new_secrets: BrokerConnectionData,
        new_meta: ConnectionMeta,
        new_available: OperationGrants,
    ) -> None:
        """Prepare, persist, activate; never roll back after an ambiguous commit.

        Disk is authoritative for recovery after activation starts. The two
        vault files are not a crash-atomic transaction; grants do not change
        here, and available operations are recomputed from the secret bundle.
        """
        broker = record.broker
        if broker is None:
            raise RpcError("UPSTREAM", "connection has no running broker")
        try:
            fields = connection_fields(entry, new_secrets)
        except BrokerSpawnError as exc:
            raise RpcError("BAD_REQUEST", "missing or invalid connection fields") from exc
        update_id = uuid4().hex
        try:
            await credential_command(broker.proc, "prepare_credentials", update_id, fields)
        except CredentialRejected as exc:
            raise RpcError(exc.code, "replacement credentials rejected; connection unchanged") from exc
        except (Exception, asyncio.CancelledError) as exc:
            record.state = "broken"
            await self._stop_record_broker(record)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RpcError("UPSTREAM", "credential preparation failed; reconnect required") from exc
        finally:
            fields.clear()

        try:
            write_secrets(self._vault_dir, record.meta.id, self._master_key, new_secrets)
            write_meta(self._vault_dir, new_meta)
        except Exception as exc:
            try:
                write_secrets(self._vault_dir, record.meta.id, self._master_key, old_secrets)
                write_meta(self._vault_dir, record.meta)
                await credential_command(broker.proc, "discard_credentials", update_id)
            except (Exception, asyncio.CancelledError) as recovery_error:
                record.state = "broken"
                await self._stop_record_broker(record)
                if isinstance(recovery_error, asyncio.CancelledError):
                    raise
                raise RpcError("INTERNAL", "credential recovery failed; reconnect required") from recovery_error
            raise RpcError("INTERNAL", "could not save credentials; connection unchanged") from exc

        record.meta = new_meta
        record.available_operations = new_available
        record.discovered_operations = connection_operations(entry, new_secrets)[1]
        try:
            await credential_command(broker.proc, "activate_credentials", update_id)
        except (Exception, asyncio.CancelledError) as exc:
            record.state = "broken"
            await self._stop_record_broker(record)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RpcError("UPSTREAM", "credentials saved but activation failed; reconnect required") from exc

    async def stop_all(self) -> None:
        """Supervisor shutdown: stop all watchers, then SIGTERM all brokers."""
        for record in self._registry.list():
            record.expected_termination = True

        watchers = list(self._watchers.values())
        for task in watchers:
            task.cancel()
        if watchers:
            await asyncio.gather(*watchers, return_exceptions=True)
        self._watchers.clear()

        for record in self._registry.list():
            if record.broker is not None:
                await self._terminate_broker(record.broker)

    # --- internals ----------------------------------------------------------

    def _start_watcher(self, connection_id: str) -> None:
        """Schedule the per-broker watcher. Idempotent: replaces an existing one."""
        existing = self._watchers.get(connection_id)
        if existing is not None and not existing.done():
            existing.cancel()
        self._watchers[connection_id] = asyncio.create_task(
            self._watch(connection_id),
            name=f"broker-watch-{connection_id}",
        )

    async def _terminate_broker(self, handle: BrokerHandle) -> None:
        """SIGTERM with grace; SIGKILL if the broker ignores us."""
        if handle.proc.returncode is None:
            handle.proc.terminate()
        try:
            await asyncio.wait_for(handle.proc.wait(), timeout=_SHUTDOWN_GRACE_SECONDS)
        except TimeoutError:
            handle.proc.kill()
            await handle.proc.wait()

    async def _stop_record_broker(self, record: BrokeredConnectionRecord) -> None:
        """Stop one record's watcher and broker without removing its registry entry."""
        connection_id = record.meta.id
        record.expected_termination = True
        watcher = self._watchers.pop(connection_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        broker = record.broker
        if broker is not None:
            await self._terminate_broker(broker)
            # Never leave a terminated process attached to a live registry
            # record. Reconnect installs a new handle only after READY and
            # successful persistence.
            record.broker = None

    async def _start_reconnected_broker(
        self,
        record: BrokeredConnectionRecord,
        entry: CatalogEntry,
        new_secrets: BrokerConnectionData,
        new_meta: ConnectionMeta,
        new_available: OperationGrants,
    ) -> None:
        """Start with replacement credentials, then save; never retry old ones."""
        connection_id = record.meta.id
        record.state = "broken"
        await self._stop_record_broker(record)
        try:
            new_handle = await spawn_broker(
                entry=entry,
                connection_id=connection_id,
                secret_bundle=new_secrets,
                operation_grants=_meta_grants(new_meta),
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                record.state = "auth_failed"
                raise RpcError("AUTH", "upstream rejected credentials") from exc
            raise RpcError("UPSTREAM", f"broker reconnect failed: {exc}") from exc
        except Exception as exc:
            raise RpcError("INTERNAL", "broker reconnect failed") from exc

        meta_saved = False
        try:
            # Each file is atomic, not the pair. Write credentials last so a
            # failed save cannot replace the old credentials. Only updated_at
            # changes in metadata; a crash between writes cannot change grants.
            write_meta(self._vault_dir, new_meta)
            meta_saved = True
            write_secrets(self._vault_dir, connection_id, self._master_key, new_secrets)
        except Exception as exc:
            await self._terminate_broker(new_handle)
            if meta_saved:
                try:
                    write_meta(self._vault_dir, record.meta)
                except Exception:
                    logger.exception("failed to restore reconnect timestamp for %s", connection_id)
            raise RpcError("INTERNAL", "could not save credentials; reconnect required") from exc

        record.broker = new_handle
        record.meta = new_meta
        record.available_operations = new_available
        record.discovered_operations = connection_operations(entry, new_secrets)[1]
        record.state = "running"
        record.expected_termination = False
        self._start_watcher(connection_id)

    async def _watch(self, connection_id: str) -> None:
        """Per-broker respawn loop with exponential backoff and circuit-breakers."""
        consecutive_failures = 0
        while True:
            record = self._registry.get(connection_id)
            if record is None:
                return
            broker = record.broker
            if broker is None:
                record.state = "broken"
                return

            try:
                exit_code = await broker.proc.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "watcher for %s failed waiting on broker", connection_id,
                )
                current = self._registry.get(connection_id)
                if current is not None and current.broker is broker:
                    current.broker = None
                    current.state = "broken"
                return

            record = self._registry.get(connection_id)
            if record is None or record.expected_termination:
                return

            logger.warning(
                "broker for %s exited unexpectedly (code=%s); attempting respawn",
                connection_id, exit_code,
            )

            if exit_code == _AUTH_FAIL_EXIT_CODE:
                logger.warning(
                    "broker for %s exited with auth-fail code %d; "
                    "marking auth_failed and stopping respawn",
                    connection_id, exit_code,
                )
                record.broker = None
                record.state = "auth_failed"
                return

            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "broker for %s failed %d times in a row; marking broken",
                    connection_id, consecutive_failures,
                )
                record.broker = None
                record.state = "broken"
                return

            backoff = min(
                _BACKOFF_CAP_SECONDS,
                _BACKOFF_BASE_SECONDS * (2 ** (consecutive_failures - 1)),
            )
            logger.info(
                "respawning broker for %s in %.1fs (attempt %d)",
                connection_id, backoff, consecutive_failures,
            )
            await asyncio.sleep(backoff)

            async with record.mutation_lock:
                if self._registry.get(connection_id) is not record or record.expected_termination:
                    return
                try:
                    new_handle = await self._respawn(connection_id, record)
                except _RespawnError as exc:
                    logger.warning("respawn failed for %s: %s", connection_id, exc)
                    if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                        record.broker = None
                        record.state = "auth_failed"
                        return
                    continue

                record.broker = new_handle
                record.state = "running"
                consecutive_failures = 0
                logger.info("respawned broker for %s", connection_id)

    async def _respawn(
        self, connection_id: str, record: BrokeredConnectionRecord,
    ) -> BrokerHandle:
        """Read secrets + spawn a fresh broker for an existing record."""
        entry = self._catalog.get(record.meta.slug)
        if entry is None:
            msg = f"catalog has no entry for slug {record.meta.slug!r}"
            raise _RespawnError(msg)

        try:
            secret_bundle = read_secrets(self._vault_dir, connection_id, self._master_key)
        except DecryptError as exc:
            msg = f"decrypt failed: {exc}"
            raise _RespawnError(msg) from exc

        try:
            secret_bundle = await self._refresh_mcp_fields(entry, connection_id, secret_bundle)
            return await spawn_broker(
                entry=entry,
                connection_id=connection_id,
                secret_bundle=secret_bundle,
                operation_grants=_meta_grants(record.meta),
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            raise _RespawnError(str(exc), exit_code=exc.exit_code) from exc


class ReconcileError(Exception):
    """Reconciliation of one integration failed.

    Reserved for persisted records that cannot be represented safely in the
    runtime registry, such as catalog drift or an unreadable credential blob.
    Broker startup failures are handled separately: reconciliation retains a
    brokerless degraded record so the UI can offer reconnect and remove.
    """


class _RespawnError(Exception):
    """Internal — wraps any failure inside :meth:`BrokerManager._respawn`."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _meta_grants(meta: ConnectionMeta) -> OperationGrants:
    if isinstance(meta, IntegrationConnectionMeta):
        return meta.agent_operation_grants
    return frozenset()


def _grants_for_add(
    entry: CatalogEntry,
    *,
    available_operations: OperationGrants,
    operation_grants: OperationGrants | None,
) -> OperationGrants:
    if isinstance(entry, ModelProviderCatalogEntry):
        if operation_grants:
            raise RpcError("BAD_REQUEST", "model providers do not have operation grants")
        return frozenset()
    if operation_grants is not None:
        return normalize_operation_grants(operation_grants, available_operations)
    return frozenset()
