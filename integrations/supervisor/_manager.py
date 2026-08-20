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
  user's recovery path is remove + re-add.
- ``broken`` — three consecutive failed respawns before READY. Likely a
  config bug or dead network path. Same recovery.

Vault I/O, catalog lookups, and ``spawn_broker`` calls all live behind
this manager. The RPC handler (``AppSockHandler``) becomes a thin
dispatcher; the supervisor lifecycle (``Supervisor.start`` / ``stop``)
owns the manager and orchestrates startup ordering.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from integrations._paths import normalize_path_prefix
from integrations._rpc import RpcError
from integrations.permissions import Access, Capability, Permissions, permissions_from_dict
from integrations.supervisor._catalog import CatalogEntry
from integrations.supervisor._crypto import DecryptError
from integrations.supervisor._registry import IntegrationRecord, Registry
from integrations.supervisor._spawn import BrokerHandle, BrokerSpawnError, spawn_broker
from integrations.supervisor.types import HostPath
from integrations.supervisor._store import (
    delete_integration,
    read_raw_meta,
    read_secrets,
    write_meta,
    write_secrets,
)
from integrations.supervisor.types import CliSecretBundle, IntegrationMeta

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
        # (scope, var_name) -> owning integration id (None for a brand-new
        # add()) claimed by an add/update that's committed past the
        # collision check but hasn't landed in the registry yet (still
        # awaiting spawn_broker). Closes the TOCTOU window the registry-only
        # check would otherwise have: two concurrent calls for the same
        # scope+name each await a real subprocess spawn before either is
        # registered, so checking the registry alone lets both pass. The
        # owner is tracked so a single integration's own overlapping update
        # calls (e.g. a double-submitted "replace secret") don't collide
        # with themselves — only a *different* caller (or another None-owner
        # add()) claiming the same key is rejected. See
        # _reserve_cli_secret_names.
        self._pending_cli_names: dict[tuple[str | None, str], str | None] = {}
        # integration_id -> the env-var names its (decrypted) bundle injects,
        # for CLI-capability integrations only. Populated whenever a CLI
        # integration's bundle becomes known (add/update/reconcile) and
        # dropped on remove. Lets the collision check compare names without
        # re-decrypting every other CLI integration's bundle on every single
        # add/update call — decryption happens once, at the point the bundle
        # is already being read/written for another reason.
        self._cli_secret_name_cache: dict[str, frozenset[str]] = {}

    # --- public lifecycle ---------------------------------------------------

    async def add(
        self,
        *,
        slug: str,
        user_suffix: str | None = None,
        label: str,
        auth_blob: dict,
        permissions: Permissions,
    ) -> IntegrationRecord:
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
        integration_id = f"{slug}_{user_suffix}" if user_suffix else slug
        if self._registry.contains(integration_id):
            raise RpcError("BAD_REQUEST", f"integration already exists: {integration_id}")

        _validate_cli_secret_bundle(entry, auth_blob)

        max_access = entry.resolve_capabilities(auth_blob)
        clamped = _clamp_permissions(permissions, max_access)

        path_prefix = _normalize_path_prefix(auth_blob.get("path_prefix"))
        reservation = self._reserve_cli_secret_names(
            entry, auth_blob, path_prefix, exclude_id=None,
        )
        with self._held_cli_secret_names(reservation):
            now = datetime.now(UTC)
            meta = IntegrationMeta(
                id=integration_id,
                slug=slug,
                label=label,
                permissions=clamped,
                path_prefix=path_prefix,
                added_at=now,
                updated_at=now,
            )

            # Write vault first. A crash between here and the spawn leaves orphaned
            # files on disk; ``reconcile_existing`` picks them up on the next boot.
            # Better than orphaning a running broker without persisted state.
            write_meta(self._vault_dir, meta)
            try:
                write_secrets(self._vault_dir, integration_id, self._master_key, auth_blob)
            except OSError as exc:
                # Meta committed but the secret didn't — don't leave a
                # half-written pair on disk (reconcile_existing would ignore
                # the orphaned .meta anyway, but there's no reason to keep it).
                delete_integration(self._vault_dir, integration_id)
                raise RpcError("INTERNAL", f"failed to write secret: {exc}") from exc

            try:
                handle = await spawn_broker(
                    entry=entry,
                    integration_id=integration_id,
                    secret_bundle=auth_blob,
                    permissions=clamped,
                    sockets_dir=self._sockets_dir,
                    host_paths=self._host_paths,
                )
            except BrokerSpawnError as exc:
                # Roll back — no broker subprocess is running at this point.
                delete_integration(self._vault_dir, integration_id)
                if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                    raise RpcError("AUTH", "upstream rejected credentials") from exc
                raise RpcError("UPSTREAM", f"broker spawn failed: {exc}") from exc

            record = IntegrationRecord(
                meta=meta,
                broker=handle,
                max_access=max_access,
            )
            self._registry.add(record)
            self._cache_cli_secret_names(entry, integration_id, auth_blob)
        self._start_watcher(integration_id)
        logger.info("added integration %s (slug=%s)", integration_id, slug)
        return record

    async def reconcile_existing(self, integration_id: str) -> IntegrationRecord:
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

        if raw.get("version", 1) < 2:
            raw = _migrate_v1_to_v2(raw, entry)

        meta = IntegrationMeta.model_validate(raw)

        try:
            secret_bundle = read_secrets(self._vault_dir, integration_id, self._master_key)
        except DecryptError as exc:
            msg = f"decrypt failed for {integration_id}: {exc}"
            raise ReconcileError(msg) from exc

        max_access = entry.resolve_capabilities(secret_bundle)
        clamped = _clamp_permissions(meta.permissions, max_access)
        if clamped != meta.permissions:
            meta = meta.model_copy(update={"permissions": clamped})
            write_meta(self._vault_dir, meta)

        # Boot reconciles every persisted integration concurrently
        # (Supervisor.start gathers reconcile_existing calls), so this is
        # exactly the same TOCTOU window add()/update() close with a
        # reservation — two persisted CLI integrations that happen to share
        # a secret-var name in the same scope (hand-edited vault, restored
        # backup) could otherwise both spawn with neither visible to the
        # other's registry-based check yet.
        try:
            reservation = self._reserve_cli_secret_names(
                entry, secret_bundle, meta.path_prefix, exclude_id=integration_id,
            )
        except RpcError as exc:
            raise ReconcileError(f"secret collision for {integration_id}: {exc.message}") from exc

        with self._held_cli_secret_names(reservation):
            try:
                handle = await spawn_broker(
                    entry=entry,
                    integration_id=integration_id,
                    secret_bundle=secret_bundle,
                    permissions=clamped,
                    sockets_dir=self._sockets_dir,
                    host_paths=self._host_paths,
                )
            except BrokerSpawnError as exc:
                kind = "auth rejected" if exc.exit_code == _AUTH_FAIL_EXIT_CODE else "spawn failed"
                msg = f"{kind} for {integration_id}: {exc}"
                raise ReconcileError(msg) from exc

            record = IntegrationRecord(
                meta=meta,
                broker=handle,
                max_access=max_access,
            )
            self._registry.add(record)
            self._cache_cli_secret_names(entry, integration_id, secret_bundle)
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
        self._cli_secret_name_cache.pop(integration_id, None)
        await self._terminate_broker(record.broker)
        delete_integration(self._vault_dir, integration_id)
        logger.info("removed integration %s", integration_id)

    async def update(
        self,
        integration_id: str,
        *,
        permissions: Permissions | None = None,
        label: str | None = None,
    ) -> IntegrationRecord:
        """Update mutable fields on an existing integration.

        Mutables today are ``permissions`` and ``label``. Both are optional
        — pass only the fields that should change. ``label`` is a string the
        broker never sees, so a label-only update rewrites the meta on disk
        and that's it. ``permissions`` is read from the broker's env at spawn
        time, so changing it means rewrite + SIGTERM + respawn with the new
        env (brief gap during which the broker socket is gone).

        There is deliberately no secret-rotation path here: swapping a
        credential (or, for a folder-scoped CLI integration, its scope) is
        remove + re-add, same as every other integration. That keeps scope
        changes an explicit, purposeful choice made at add-time instead of
        something a partial-update payload could shift by omission, and
        keeps this method's failure modes simple — there's no prior secret
        to lose if a rewrite-then-respawn here goes wrong.

        Raises :class:`RpcError` (NOT_FOUND) if the id isn't registered.
        Returns the updated record on success. If the respawn fails, the
        meta on disk has the new value and the in-memory record is marked
        ``broken``; the caller's recovery path is remove + re-add.
        """
        record = self._registry.get(integration_id)
        if record is None:
            raise RpcError("NOT_FOUND", f"unknown integration: {integration_id}")

        if permissions is None and label is None:
            raise RpcError("BAD_REQUEST", "update requires at least one field")

        if label is not None and not label:
            raise RpcError("BAD_REQUEST", "'label' must be a non-empty string")

        if permissions is not None:
            permissions = _clamp_permissions(permissions, record.max_access)

        perms_changed = (
            permissions is not None and record.meta.permissions != permissions
        )
        label_changed = label is not None and record.meta.label != label

        # No-op shortcut: nothing actually different, skip the work.
        if not perms_changed and not label_changed:
            return record

        meta_updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if perms_changed:
            meta_updates["permissions"] = permissions
        if label_changed:
            meta_updates["label"] = label
        new_meta = record.meta.model_copy(update=meta_updates)
        # Commit the meta change before we touch the running process. If we
        # crash between this write and a respawn, the next reconcile picks
        # up the new value.
        write_meta(self._vault_dir, new_meta)

        # Label-only: no env change, no respawn. Update in place and return.
        if not perms_changed:
            record.meta = new_meta
            logger.info("updated integration %s (label=%r)", integration_id, label)
            return record

        # Permissions changed — broker needs a new env, which means respawn.
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
        except DecryptError as exc:
            raise RpcError("INTERNAL", f"decrypt failed: {exc}") from exc

        # Stop the watcher and terminate before respawn — same dance as
        # remove(), but we keep the registry entry so the new handle slots
        # back in under the same id.
        record.expected_termination = True
        watcher = self._watchers.pop(integration_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await self._terminate_broker(record.broker)

        try:
            new_handle = await spawn_broker(
                entry=entry,
                integration_id=integration_id,
                secret_bundle=secret_bundle,
                permissions=new_meta.permissions,
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            # New meta is on disk, but we have no live broker. Mark broken
            # so list/resolve surface the failure; user remediation is
            # remove + re-add.
            record.state = "broken"
            if exc.exit_code == _AUTH_FAIL_EXIT_CODE:
                record.state = "auth_failed"
                raise RpcError("AUTH", "upstream rejected credentials") from exc
            raise RpcError("UPSTREAM", f"broker respawn failed: {exc}") from exc

        # Reset terminal-state flags now that the new broker is live.
        record.broker = new_handle
        record.meta = new_meta
        record.state = "running"
        record.expected_termination = False
        self._start_watcher(integration_id)
        logger.info(
            "updated integration %s (permissions=%s, label=%r)",
            integration_id, new_meta.permissions, new_meta.label,
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
            await self._terminate_broker(record.broker)

    def _reserve_cli_secret_names(
        self,
        entry: CatalogEntry,
        auth_blob: dict,
        path_prefix: str | None,
        *,
        exclude_id: str | None,
    ) -> frozenset[tuple[str | None, str]]:
        """Check for CLI secret-name collisions and atomically claim the new names.

        Wraps ``_check_cli_secret_collisions`` (which only sees integrations
        already in the registry) with a check against ``_pending_cli_names``
        — names claimed by another add/update that's past its own check but
        hasn't reached the registry yet (still awaiting the real
        ``spawn_broker`` subprocess call). The check and the claim happen in
        the same synchronous call with no ``await`` in between, so two
        concurrent RPCs for the same scope+name can't both pass: whichever
        coroutine runs this method first claims the name before yielding
        control back to the event loop.

        Callers must release the returned reservation (via
        ``_release_cli_secret_names``) in a ``finally`` block once the
        integration is either registered or the attempt is abandoned.
        """
        new_names = _cli_secret_names(entry, auth_blob)
        if not new_names:
            return frozenset()
        self._check_cli_secret_collisions(entry, auth_blob, path_prefix, exclude_id=exclude_id)
        for name in new_names:
            owner = self._pending_cli_names.get((path_prefix, name))
            # Blocks unless this exact key is already pending *for me* (the
            # same non-None exclude_id) — a None owner (someone else's
            # add()) or a different owner always collides, even when my own
            # exclude_id is None, so two concurrent add()s for the same new
            # key still correctly collide with each other.
            if (path_prefix, name) in self._pending_cli_names and (owner is None or owner != exclude_id):
                raise RpcError(
                    "BAD_REQUEST",
                    f"env var {name!r} is already being added for this scope "
                    "by a concurrent request",
                )
        reservation = frozenset((path_prefix, name) for name in new_names)
        self._pending_cli_names.update({key: exclude_id for key in reservation})
        return reservation

    def _release_cli_secret_names(self, reservation: frozenset[tuple[str | None, str]]) -> None:
        """Release a reservation from ``_reserve_cli_secret_names``. No-op for an empty set."""
        for key in reservation:
            self._pending_cli_names.pop(key, None)

    @contextmanager
    def _held_cli_secret_names(
        self, reservation: frozenset[tuple[str | None, str]],
    ) -> Iterator[None]:
        """Guarantee ``_release_cli_secret_names`` runs when the protected block exits.

        Callers still acquire the reservation themselves via
        ``_reserve_cli_secret_names`` (its ``RpcError`` on collision is
        call-site-specific to handle), then wrap the risky work — persist,
        spawn, register — in ``with self._held_cli_secret_names(reservation):``
        instead of a hand-rolled ``try/finally``. One release path shared by
        every call site means a future one can't add itself without the
        release, the way a copy-pasted ``try/finally`` could silently drop it.
        """
        try:
            yield
        finally:
            self._release_cli_secret_names(reservation)

    def _cache_cli_secret_names(self, entry: CatalogEntry, integration_id: str, auth_blob: dict) -> None:
        """Record ``integration_id``'s injected env-var names for the collision check.

        Call this once, right after a bundle is written or freshly decrypted
        for another reason (add, secret rotation, reconcile) — never as a
        reason to decrypt on its own. A non-CLI integration (or one with no
        names) stores an empty set, which the collision check's ``if not
        other_names: continue`` treats the same as "not present".
        """
        self._cli_secret_name_cache[integration_id] = _cli_secret_names(entry, auth_blob)

    def _check_cli_secret_collisions(
        self,
        entry: CatalogEntry,
        auth_blob: dict,
        path_prefix: str | None,
        *,
        exclude_id: str | None,
    ) -> None:
        """Guard CLI-exec secret var names against collisions with other CLI integrations.

        Var names aren't visible to the app server (they live inside the
        encrypted bundle, same as any other secret), so this check depends
        on ``_cli_secret_name_cache`` — populated whenever a CLI
        integration's bundle is written or read for another reason, not
        decrypted fresh here. Two integrations defining the same var name in
        the *same* scope (both global, or the same path prefix) is rejected
        outright — the broker spawn order would make the outcome
        nondeterministic. The same name in *different* scopes is allowed (a
        folder-scoped var legitimately shadows a global one for that folder)
        but logged — key name only, never the value.
        """
        new_names = _cli_secret_names(entry, auth_blob)
        if not new_names:
            return
        for other in self._registry.list():
            if other.meta.id == exclude_id:
                continue
            other_names = self._cli_secret_name_cache.get(other.meta.id)
            if not other_names:
                continue
            overlap = new_names & other_names
            if not overlap:
                continue
            if path_prefix == other.meta.path_prefix:
                raise RpcError(
                    "BAD_REQUEST",
                    f"env var(s) {sorted(overlap)} already defined for this "
                    f"scope by integration {other.meta.id!r}",
                )
            logger.warning(
                "cli secret var(s) %s shadow existing integration %s "
                "(new scope=%r, existing scope=%r)",
                sorted(overlap), other.meta.id, path_prefix, other.meta.path_prefix,
            )

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

    async def _watch(self, integration_id: str) -> None:
        """Per-broker respawn loop with exponential backoff and circuit-breakers."""
        consecutive_failures = 0
        while True:
            record = self._registry.get(integration_id)
            if record is None:
                return

            try:
                exit_code = await record.broker.proc.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "watcher for %s failed waiting on broker", integration_id,
                )
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
                record.state = "auth_failed"
                return

            consecutive_failures += 1
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "broker for %s failed %d times in a row; marking broken",
                    integration_id, consecutive_failures,
                )
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
                    record.state = "auth_failed"
                    return
                continue

            record.broker = new_handle
            record.state = "running"
            consecutive_failures = 0
            logger.info("respawned broker for %s", integration_id)

    async def _respawn(
        self, integration_id: str, record: IntegrationRecord,
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
                permissions=record.meta.permissions,
                sockets_dir=self._sockets_dir,
                host_paths=self._host_paths,
            )
        except BrokerSpawnError as exc:
            raise _RespawnError(str(exc), exit_code=exc.exit_code) from exc


class ReconcileError(Exception):
    """Reconciliation of one integration failed.

    Causes are catalog drift (slug removed since registration), decrypt
    error, or spawn failure (auth rejected, READY timeout, etc.). The
    supervisor logs and skips, leaving the vault files intact so the
    user can recover via remove + re-add.
    """


class _RespawnError(Exception):
    """Internal — wraps any failure inside :meth:`BrokerManager._respawn`."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _cli_secret_names(entry: CatalogEntry, auth_blob: dict) -> frozenset[str]:
    """Env-var names a CLI-exec integration's bundle would inject.

    Empty for anything that isn't a ``Capability.CLI`` provider — those
    never participate in the collision check. The names come from the
    bundle's own ``vars`` (user-defined at add-time), not the catalog —
    every CLI integration is a dynamic-spawn entry: the binary and its
    secrets are whatever the user configured, not a fixed per-tool catalog
    entry.
    """
    if Capability.CLI not in entry.capabilities:
        return frozenset()
    variables = auth_blob.get("vars")
    return frozenset(variables) if isinstance(variables, dict) else frozenset()


def _validate_cli_secret_bundle(entry: CatalogEntry, auth_blob: dict) -> None:
    """Reject a malformed ``auth_blob`` for a CLI-capability integration.

    A no-op for every other capability — those keep their existing loosely-
    typed ``dict`` handling. Raises :class:`RpcError` (``BAD_REQUEST``) with
    a message built from the pydantic validation errors so the caller sees
    exactly which field was wrong, instead of the bundle silently reaching
    the vault or a subprocess env with e.g. a non-list command.
    """
    if Capability.CLI not in entry.capabilities:
        return
    try:
        bundle = CliSecretBundle.model_validate(auth_blob)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise RpcError("BAD_REQUEST", f"invalid auth_blob: {details}") from exc
    if not bundle.command:
        raise RpcError("BAD_REQUEST", "invalid auth_blob: command: field required")


def _normalize_path_prefix(raw: object) -> str | None:
    """Collapse a path-prefix value to its canonical stored form.

    ``None`` for anything absent/blank/non-string; otherwise the shared
    ``normalize_path_prefix`` result, so this is the exact same canonical
    form the broker enforces against — the UI already normalizes before
    submitting, but a direct API/RPC caller doesn't have to.
    """
    if not isinstance(raw, str):
        return None
    return normalize_path_prefix(raw) or None


def _clamp_permissions(
    requested: Permissions,
    max_access: dict[Capability, Access],
) -> Permissions:
    """Enforce the provider's limits on what the user asked for.

    For each capability the provider supports, use the user's choice or
    OFF if they didn't mention it. If they asked for more than the
    provider allows (e.g. read+write on a read-only scope), lower it to
    the max. Capabilities the provider doesn't support are ignored.
    """
    clamped: Permissions = {}
    for cap, cap_max in max_access.items():
        requested_access = requested.get(cap, Access.OFF)
        clamped[cap] = min(requested_access, cap_max)
    return clamped


def _migrate_v1_to_v2(raw: dict, entry: CatalogEntry) -> dict:
    """Upgrade a v1 meta dict to v2 shape in memory.

    v1 stored ``write_allowed: bool``. v2 stores per-capability
    ``permissions``. The catalog entry tells us which capabilities this
    slug actually supports, so we only set those.
    """
    write_allowed = raw.pop("write_allowed", False)
    access = "rw" if write_allowed else "r"
    raw["permissions"] = {cap.value: access for cap in entry.capabilities}
    raw["version"] = 2
    logger.info(
        "migrated meta for %s from v1 (write_allowed=%s) to v2",
        raw.get("id", "?"), write_allowed,
    )
    return raw
