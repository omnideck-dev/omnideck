"""In-memory record of which integrations are currently available.

Tracks one :class:`RegisteredIntegration` per active integration, keyed by
ID. The cache loads on first read: :func:`registered_integrations` calls
:func:`_ensure_loaded`, which kicks off the supervisor probe on the first
call and awaits its completion (with a short timeout) before returning.
Every tool-catalog resolution refreshes from the supervisor so asynchronous
broker state changes (auth failure, crash circuit-breaker) cannot leave stale
tools exposed. Concurrent readers share the same in-flight refresh.
"""

from __future__ import annotations

import asyncio
import logging

from config import load_config
from integrations import supervisor_client
from integrations.operation_grants import OperationGrants
from integrations.supervisor_client import SupervisorError
from tools.integrations.types import RegisteredIntegration

logger = logging.getLogger(__name__)

_LOAD_WAIT_SECONDS = 5.0

_registered: dict[str, RegisteredIntegration] = {}
_load_future: asyncio.Future[None] | None = None


def cache_loaded() -> bool:
    """True iff the most recent load attempt succeeded.

    Failure paths in :func:`refresh_registered_integrations` clear the
    in-flight future, so this only returns True after the cache reflects
    the supervisor's state at least once. An empty cache after a successful
    load (no integrations registered) still counts as loaded.
    """
    future = _load_future
    return (
        future is not None
        and future.done()
        and not future.cancelled()
        and future.exception() is None
    )


def mark_added(
    integration_id: str,
    slug: str,
    operation_grants: OperationGrants,
    state: str = "running",
    *,
    kind: str = "integration",
) -> None:
    """Record that an integration has been successfully added."""
    _registered[integration_id] = RegisteredIntegration(
        id=integration_id,
        slug=slug,
        kind=kind,
        operation_grants=frozenset(operation_grants),
        state=state if isinstance(state, str) else "running",
    )


def mark_removed(integration_id: str) -> None:
    """Record that an integration has been removed. No-op if unknown."""
    _registered.pop(integration_id, None)


async def registered_integrations() -> dict[str, RegisteredIntegration]:
    """Snapshot of currently registered integrations, keyed by ID.

    Returns a fresh dict — callers can iterate, filter by operation, or
    look up a specific record without coordinating with internal state.
    """
    await _ensure_loaded(force_refresh=True)
    return dict(_registered)


async def _ensure_loaded(*, force_refresh: bool = False) -> None:
    """Refresh the cache and share an already in-flight supervisor request.

    A completed load is reused only by startup callers that do not request a
    refresh. Normal tool resolution forces a new snapshot, while simultaneous
    readers still await one shared task.
    """
    global _load_future
    if _load_future is None or (force_refresh and _load_future.done()):
        _load_future = asyncio.ensure_future(refresh_registered_integrations())
    load_future = _load_future
    if load_future.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(load_future), timeout=_LOAD_WAIT_SECONDS)
    except TimeoutError:
        _registered.clear()
        logger.warning(
            "integrations cache still loading after %.1fs; tools may be hidden this turn",
            _LOAD_WAIT_SECONDS,
        )


async def refresh_registered_integrations() -> None:
    """Resync the in-memory list of integrations from the source of truth.

    On transport failure or a supervisor-side error, clears the in-flight
    load future so the *next* caller re-triggers — protects against the
    startup race where the app's first load fires before the supervisor
    has bound its socket.
    """
    global _load_future
    sock_path = load_config().integrations.app_sock_path
    try:
        result = await supervisor_client.call(
            "list", {"kind": "integration"}, app_sock_path=sock_path,
        )
        snapshot = _snapshot_from_result(result)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
        logger.warning(
            "integrations source not reachable at %s (%s); "
            "integration tools hidden until next successful refresh",
            sock_path, exc,
        )
        _registered.clear()
        _load_future = None
        return
    except SupervisorError as exc:
        logger.warning("list error from integrations source: %s: %s", exc.code, exc.message)
        _registered.clear()
        _load_future = None
        return
    except Exception:  # noqa: BLE001
        # Treat malformed or otherwise unexpected supervisor responses as a
        # failed snapshot. Tool exposure must fail closed, and clearing the
        # future lets a later resolution retry after a transient protocol bug.
        logger.exception("unexpected error refreshing the integrations cache")
        _registered.clear()
        _load_future = None
        return

    _registered.clear()
    _registered.update(snapshot)

    logger.info("loaded %d registered integration(s)", len(_registered))


def _snapshot_from_result(result: object) -> dict[str, RegisteredIntegration]:
    """Validate a supervisor list response before replacing the live cache."""
    if not isinstance(result, dict):
        raise TypeError("integration list response must be an object")
    entries = result.get("connections") or result.get("integrations", [])
    if not isinstance(entries, list):
        raise TypeError("integration list response must contain an array")

    snapshot: dict[str, RegisteredIntegration] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("integration list entries must be objects")
        integration_id = entry.get("id")
        slug = entry.get("slug")
        if not (isinstance(integration_id, str) and isinstance(slug, str)):
            continue
        grants_raw = entry.get("operation_grants")
        grants = frozenset(grants_raw) if isinstance(grants_raw, list) else frozenset()
        snapshot[integration_id] = RegisteredIntegration(
            id=integration_id,
            slug=slug,
            operation_grants=grants,
            state=entry.get("state") or "running",
            kind=entry.get("kind") or "integration",
        )
    return snapshot
