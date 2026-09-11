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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from integrations._rpc import RpcError
from integrations.catalog import (
    CatalogEntry,
    IntegrationCatalogEntry,
    ModelProviderCatalogEntry,
)
from integrations.operation_grants import (
    OperationGrants,
    legacy_permissions_to_operation_grants,
    legacy_v1_to_operation_grants,
    normalize_operation_grants,
)
from integrations.permissions import Permissions, permissions_from_dict
from integrations.supervisor._crypto import DecryptError
from integrations.supervisor._registry import BrokeredConnectionRecord, Registry
from integrations.supervisor._spawn import BrokerHandle, BrokerSpawnError, spawn_broker
from integrations.supervisor._store import (
    backup_meta_before_v3,
    delete_integration,
    read_raw_meta,
    read_secrets,
    write_meta,
    write_secrets,
)
from integrations.supervisor.types import (
    ConnectionMeta,
    HostPath,
    IntegrationMeta,
    ModelProviderMeta,
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
        auth_blob: dict,
        operation_grants: OperationGrants | None = None,
        permissions: Permissions | None = None,
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
        if not isinstance(auth_blob, dict):
            raise RpcError("BAD_REQUEST", "auth_blob must be a dict")

        entry = self._catalog[slug]
        if kind is not None and kind != entry.kind:
            raise RpcError("BAD_REQUEST", f"catalog entry {slug!r} has kind {entry.kind!r}")
        if operation_grants is not None and permissions is not None:
            raise RpcError("BAD_REQUEST", "provide operation_grants or permissions, not both")
        integration_id = f"{slug}_{user_suffix}" if user_suffix else slug
        if self._registry.contains(integration_id):
            raise RpcError("BAD_REQUEST", f"integration already exists: {integration_id}")

        available_operations = entry.resolve_operations(auth_blob)
        grants = _grants_for_add(
            entry,
            available_operations=available_operations,
            operation_grants=operation_grants,
            permissions=permissions,
        )

        now = datetime.now(UTC)
        common = {
            "id": integration_id,
            "slug": slug,
            "label": label,
            "added_at": now,
            "updated_at": now,
        }
        meta: ConnectionMeta
        if isinstance(entry, IntegrationCatalogEntry):
            meta = IntegrationMeta(**common, agent_operation_grants=grants)
        else:
            meta = ModelProviderMeta(**common)

        # Write vault first. A crash between here and the spawn leaves orphaned
        # files on disk; ``reconcile_existing`` picks them up on the next boot.
        # Better than orphaning a running broker without persisted state.
        write_meta(self._vault_dir, meta)
        write_secrets(self._vault_dir, integration_id, self._master_key, auth_blob)

        try:
            handle = await spawn_broker(
                entry=entry,
                integration_id=integration_id,
                secret_bundle=auth_blob,
                operation_grants=grants,
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            # Roll back — no broker subprocess is running at this point.
            delete_integration(self._vault_dir, integration_id)
            if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                raise RpcError("AUTH", "upstream rejected credentials") from exc
            raise RpcError("UPSTREAM", f"broker spawn failed: {exc}") from exc

        record = BrokeredConnectionRecord(
            meta=meta,
            broker=handle,
            available_operations=available_operations,
        )
        self._registry.add(record)
        self._start_watcher(integration_id)
        logger.info("added integration %s (slug=%s)", integration_id, slug)
        return record

    async def reconcile_existing(self, integration_id: str) -> BrokeredConnectionRecord:
        """Re-spawn a broker for an integration already persisted in the vault.

        Raises :class:`ReconcileError` on any failure path so the caller
        (Supervisor.start) can log and skip a single bad integration without
        bringing the whole supervisor down.
        """
        raw = read_raw_meta(self._vault_dir, integration_id)

        slug = raw.get("slug", "")
        entry = self._catalog.get(slug)
        if entry is None:
            msg = f"catalog has no entry for slug {slug!r}"
            raise ReconcileError(msg)

        try:
            secret_bundle = read_secrets(self._vault_dir, integration_id, self._master_key)
        except DecryptError as exc:
            msg = f"decrypt failed for {integration_id}: {exc}"
            raise ReconcileError(msg) from exc

        available_operations = entry.resolve_operations(secret_bundle)
        schema_migrated = raw.get("version", 1) < 3
        metadata_changed = schema_migrated
        if schema_migrated:
            raw = _migrate_to_v3(raw, entry, available_operations)
        meta = connection_meta_from_dict(raw)

        expected_kind = entry.kind
        if meta.kind != expected_kind:
            raise ReconcileError(
                f"metadata kind {meta.kind!r} does not match catalog kind {expected_kind!r}",
            )

        if isinstance(meta, IntegrationMeta):
            normalized = normalize_operation_grants(
                meta.agent_operation_grants, available_operations,
            )
            if normalized != meta.agent_operation_grants:
                meta = meta.model_copy(update={"agent_operation_grants": normalized})
                metadata_changed = True

        if metadata_changed:
            if schema_migrated:
                backup_meta_before_v3(self._vault_dir, integration_id)
            write_meta(self._vault_dir, meta)

        try:
            handle = await spawn_broker(
                entry=entry,
                integration_id=integration_id,
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
            )
            self._registry.add(record)
            logger.warning(
                "%s for %s; retaining %s record for recovery: %s",
                kind,
                integration_id,
                state,
                exc,
            )
            return record

        record = BrokeredConnectionRecord(
            meta=meta,
            broker=handle,
            available_operations=available_operations,
        )
        self._registry.add(record)
        self._start_watcher(integration_id)
        logger.info("reconciled %s (slug=%s)", integration_id, meta.slug)
        return record

    async def remove(self, integration_id: str) -> None:
        """Tear down an integration: stop watcher, SIGTERM, drop registry, wipe vault.

        Raises :class:`RpcError` (NOT_FOUND) if the id isn't registered.
        """
        record = self._registry.get(integration_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {integration_id}")

        # Flag the record first so the watcher sees expected_termination on
        # the next iteration (or already-pending wait), then cancel its task
        # so the SIGTERM below isn't read as a crash.
        record.expected_termination = True
        watcher = self._watchers.pop(integration_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

        self._registry.remove(integration_id)
        if record.broker is not None:
            await self._terminate_broker(record.broker)
        delete_integration(self._vault_dir, integration_id)
        logger.info("removed integration %s", integration_id)

    async def update(
        self,
        integration_id: str,
        *,
        operation_grants: OperationGrants | None = None,
        permissions: Permissions | None = None,
        label: str | None = None,
    ) -> BrokeredConnectionRecord:
        """Update mutable fields on an existing integration.

        Mutables are explicit operation grants and ``label``. The deprecated
        ``permissions`` is accepted only for backward-compatible clients. A label
        change is metadata-only; a grant change respawns the broker with the
        new exact allowlist.

        Raises :class:`RpcError` (NOT_FOUND) if the id isn't registered.
        Returns the updated record on success. A failed respawn restores the
        previous metadata and process before returning the error.
        """
        record = self._registry.get(integration_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {integration_id}")

        if operation_grants is not None and permissions is not None:
            raise RpcError("BAD_REQUEST", "provide operation_grants or permissions, not both")

        if operation_grants is None and permissions is None and label is None:
            raise RpcError("BAD_REQUEST", "update requires at least one field")

        if label is not None and not label.strip():
            raise RpcError("BAD_REQUEST", "'label' must be a non-empty string")

        requested_grants: OperationGrants | None = None
        if operation_grants is not None or permissions is not None:
            if not isinstance(record.meta, IntegrationMeta):
                raise RpcError("BAD_REQUEST", "model providers do not have operation grants")
            requested_grants = (
                normalize_operation_grants(operation_grants, record.available_operations)
                if operation_grants is not None
                else legacy_permissions_to_operation_grants(
                    permissions or {}, record.available_operations,
                )
            )

        grants_changed = (
            requested_grants is not None
            and isinstance(record.meta, IntegrationMeta)
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
            logger.info("updated integration %s (label=%r)", integration_id, label)
            return record

        # Grants changed — broker needs a new env, which means respawn.
        entry = self._catalog.get(record.meta.slug)
        if entry is None:
            raise RpcError(
                "BAD_REQUEST",
                f"catalog has no entry for slug {record.meta.slug!r}",
            )

        try:
            secret_bundle = read_secrets(
                self._vault_dir, integration_id, self._master_key,
            )
        except (DecryptError, OSError) as exc:
            raise RpcError("INTERNAL", f"decrypt failed: {exc}") from exc

        await self._replace_broker_transactionally(
            record,
            entry=entry,
            old_secret_bundle=secret_bundle,
            new_secret_bundle=secret_bundle,
            new_meta=new_meta,
            new_available_operations=record.available_operations,
            persist_new_secrets=False,
            failure_label="broker grant update",
        )
        logger.info(
            "updated integration %s (operation_grants=%s, label=%r)",
            integration_id, sorted(_meta_grants(new_meta)), new_meta.label,
        )
        return record

    async def reconnect(
        self,
        integration_id: str,
        *,
        auth_blob: dict,
        kind: ConnectionKind | None = None,
    ) -> BrokeredConnectionRecord:
        """Replace credentials and restart an existing brokered connection.

        Tool integrations preserve exact grants when the new remote
        authorization still supports them and narrow them otherwise. Model
        providers share the same transactional credential replacement but do
        not carry operation grants.
        """
        record = self._registry.get(integration_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {integration_id}")
        if kind is not None and record.meta.kind != kind:
            raise RpcError(
                "BAD_REQUEST",
                f"connection {integration_id!r} has kind {record.meta.kind!r}",
            )
        if not isinstance(auth_blob, dict):
            raise RpcError("BAD_REQUEST", "auth_blob must be a dict")

        entry = self._catalog.get(record.meta.slug)
        if entry is None or entry.kind != record.meta.kind:
            raise RpcError(
                "BAD_REQUEST",
                f"catalog has no {record.meta.kind!r} entry for slug {record.meta.slug!r}",
            )
        try:
            old_secrets = read_secrets(
                self._vault_dir, integration_id, self._master_key,
            )
        except (DecryptError, OSError) as exc:
            raise RpcError("INTERNAL", f"decrypt failed: {exc}") from exc

        old_meta = record.meta
        new_available = entry.resolve_operations(auth_blob)
        if isinstance(old_meta, IntegrationMeta):
            new_grants = normalize_operation_grants(
                old_meta.agent_operation_grants, new_available,
            )
            new_meta = old_meta.model_copy(update={
                "agent_operation_grants": new_grants,
                "updated_at": datetime.now(UTC),
            })
        else:
            new_grants = frozenset()
            new_meta = old_meta.model_copy(update={"updated_at": datetime.now(UTC)})

        await self._replace_broker_transactionally(
            record,
            entry=entry,
            old_secret_bundle=old_secrets,
            new_secret_bundle=auth_blob,
            new_meta=new_meta,
            new_available_operations=new_available,
            persist_new_secrets=True,
            failure_label="broker reconnect",
        )
        logger.info(
            "reconnected %s %s (operation_grants=%s)",
            record.meta.kind, integration_id, sorted(new_grants),
        )
        return record

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

    def _start_watcher(self, integration_id: str) -> None:
        """Schedule the per-broker watcher. Idempotent: replaces an existing one."""
        existing = self._watchers.get(integration_id)
        if existing is not None and not existing.done():
            existing.cancel()
        self._watchers[integration_id] = asyncio.create_task(
            self._watch(integration_id),
            name=f"broker-watch-{integration_id}",
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
        integration_id = record.meta.id
        record.expected_termination = True
        watcher = self._watchers.pop(integration_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        broker = record.broker
        if broker is not None:
            await self._terminate_broker(broker)
            # Never leave a terminated process attached to a live registry
            # record. Replacement and rollback paths install their new handle
            # only after its READY handshake succeeds.
            record.broker = None

    async def _replace_broker_transactionally(
        self,
        record: BrokeredConnectionRecord,
        *,
        entry: CatalogEntry,
        old_secret_bundle: dict,
        new_secret_bundle: dict,
        new_meta: ConnectionMeta,
        new_available_operations: OperationGrants,
        persist_new_secrets: bool,
        failure_label: str,
    ) -> None:
        """Replace a broker and roll back policy, secrets, and process on failure."""
        integration_id = record.meta.id
        old_meta = record.meta
        old_available = record.available_operations

        await self._stop_record_broker(record)
        try:
            if persist_new_secrets:
                write_secrets(
                    self._vault_dir,
                    integration_id,
                    self._master_key,
                    new_secret_bundle,
                )
            write_meta(self._vault_dir, new_meta)
            new_handle = await spawn_broker(
                entry=entry,
                integration_id=integration_id,
                secret_bundle=new_secret_bundle,
                operation_grants=_meta_grants(new_meta),
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except Exception as exc:  # noqa: BLE001 - rollback every replacement failure
            await self._restore_replaced_broker(
                record,
                entry=entry,
                old_secret_bundle=old_secret_bundle,
                old_meta=old_meta,
                old_available_operations=old_available,
                restore_secrets=persist_new_secrets,
            )
            if isinstance(exc, BrokerSpawnError):
                if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                    raise RpcError("AUTH", "upstream rejected credentials") from exc
                raise RpcError("UPSTREAM", f"{failure_label} failed: {exc}") from exc
            raise RpcError("INTERNAL", f"{failure_label} failed: {exc}") from exc

        record.broker = new_handle
        record.meta = new_meta
        record.available_operations = new_available_operations
        record.state = "running"
        record.expected_termination = False
        self._start_watcher(integration_id)

    async def _restore_replaced_broker(
        self,
        record: BrokeredConnectionRecord,
        *,
        entry: CatalogEntry,
        old_secret_bundle: dict,
        old_meta: ConnectionMeta,
        old_available_operations: OperationGrants,
        restore_secrets: bool,
    ) -> None:
        """Best-effort rollback used when a replacement broker cannot start."""
        integration_id = old_meta.id
        storage_error: Exception | None = None
        try:
            if restore_secrets:
                write_secrets(
                    self._vault_dir,
                    integration_id,
                    self._master_key,
                    old_secret_bundle,
                )
            write_meta(self._vault_dir, old_meta)
        except Exception as exc:  # noqa: BLE001 - keep attempting process restore
            storage_error = exc
            logger.exception("failed to restore vault state for %s", integration_id)

        record.meta = old_meta
        record.available_operations = old_available_operations
        record.expected_termination = False
        if storage_error is not None:
            # Disk state is no longer known to match either side of the
            # replacement. Keep the connection visible for reconnect/remove,
            # but do not start an unmonitored process from the in-memory copy.
            record.state = "broken"
            return
        try:
            restored_handle = await spawn_broker(
                entry=entry,
                integration_id=integration_id,
                secret_bundle=old_secret_bundle,
                operation_grants=_meta_grants(old_meta),
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except Exception as exc:  # noqa: BLE001 - terminal rollback failure
            record.broker = None
            record.state = (
                "auth_failed"
                if isinstance(exc, BrokerSpawnError)
                and exc.exit_code == _AUTH_FAIL_EXIT_CODE
                else "broken"
            )
            logger.exception("failed to restore previous broker for %s", integration_id)
            return

        record.broker = restored_handle
        record.state = "running"
        self._start_watcher(integration_id)

    async def _watch(self, integration_id: str) -> None:
        """Per-broker respawn loop with exponential backoff and circuit-breakers."""
        consecutive_failures = 0
        while True:
            record = self._registry.get(integration_id)
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
                    "watcher for %s failed waiting on broker", integration_id,
                )
                current = self._registry.get(integration_id)
                if current is not None and current.broker is broker:
                    current.broker = None
                    current.state = "broken"
                return

            record = self._registry.get(integration_id)
            if record is None or record.expected_termination:
                return

            logger.warning(
                "broker for %s exited unexpectedly (code=%s); attempting respawn",
                integration_id, exit_code,
            )

            if exit_code == _AUTH_FAIL_EXIT_CODE:
                logger.warning(
                    "broker for %s exited with auth-fail code %d; "
                    "marking auth_failed and stopping respawn",
                    integration_id, exit_code,
                )
                record.broker = None
                record.state = "auth_failed"
                return

            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "broker for %s failed %d times in a row; marking broken",
                    integration_id, consecutive_failures,
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
                integration_id, backoff, consecutive_failures,
            )
            await asyncio.sleep(backoff)

            try:
                new_handle = await self._respawn(integration_id, record)
            except _RespawnError as exc:
                logger.warning("respawn failed for %s: %s", integration_id, exc)
                if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                    record.broker = None
                    record.state = "auth_failed"
                    return
                continue

            record.broker = new_handle
            record.state = "running"
            consecutive_failures = 0
            logger.info("respawned broker for %s", integration_id)

    async def _respawn(
        self, integration_id: str, record: BrokeredConnectionRecord,
    ) -> BrokerHandle:
        """Read secrets + spawn a fresh broker for an existing record."""
        entry = self._catalog.get(record.meta.slug)
        if entry is None:
            msg = f"catalog has no entry for slug {record.meta.slug!r}"
            raise _RespawnError(msg)

        try:
            secret_bundle = read_secrets(self._vault_dir, integration_id, self._master_key)
        except DecryptError as exc:
            msg = f"decrypt failed: {exc}"
            raise _RespawnError(msg) from exc

        try:
            return await spawn_broker(
                entry=entry,
                integration_id=integration_id,
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
    if isinstance(meta, IntegrationMeta):
        return meta.agent_operation_grants
    return frozenset()


def _grants_for_add(
    entry: CatalogEntry,
    *,
    available_operations: OperationGrants,
    operation_grants: OperationGrants | None,
    permissions: Permissions | None,
) -> OperationGrants:
    if isinstance(entry, ModelProviderCatalogEntry):
        if operation_grants or permissions:
            raise RpcError("BAD_REQUEST", "model providers do not have operation grants")
        return frozenset()
    if operation_grants is not None:
        return normalize_operation_grants(operation_grants, available_operations)
    if permissions is not None:
        return legacy_permissions_to_operation_grants(permissions, available_operations)
    return frozenset()


def _migrate_to_v3(
    raw: dict[str, Any],
    entry: CatalogEntry,
    available_operations: OperationGrants,
) -> dict[str, Any]:
    """Deterministically upgrade v1/v2 metadata to the operation model."""
    migrated = dict(raw)
    previous_version = migrated.get("version", 1)
    migrated["version"] = 3
    migrated["kind"] = entry.kind

    if isinstance(entry, ModelProviderCatalogEntry):
        migrated.pop("permissions", None)
        migrated.pop("write_allowed", None)
        migrated.pop("agent_operation_grants", None)
    else:
        if previous_version < 2:
            write_allowed = bool(migrated.pop("write_allowed", False))
            grants = legacy_v1_to_operation_grants(
                write_allowed=write_allowed,
                available_operations=available_operations,
            )
        else:
            legacy_raw = migrated.pop("permissions", {})
            permissions = permissions_from_dict(legacy_raw) if isinstance(legacy_raw, dict) else {}
            grants = legacy_permissions_to_operation_grants(
                permissions, available_operations,
            )
        migrated["agent_operation_grants"] = sorted(grants)

    logger.info(
        "migrated metadata for %s from v%s to v3 (%s)",
        migrated.get("id", "?"), previous_version, entry.kind,
    )
    return migrated
