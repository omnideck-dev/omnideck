"""In-memory registry mapping connection IDs to running broker handles.

State is intentionally non-persistent. On supervisor restart we rebuild by
re-reading ``.meta`` files and respawning brokers — fresh process, fresh state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from integrations.operation_grants import OperationGrants
from brokering.supervisor._spawn import BrokerHandle
from brokering.supervisor.types import ConnectionMeta

ConnectionState = Literal["running", "auth_failed", "broken"]


@dataclass
class BrokeredConnectionRecord:
    """In-memory state for one active integration or model provider.

    Pairs persisted domain metadata with an optional live ``BrokerHandle`` and
    the operations currently available under the remote authorization. A
    brokerless record represents a connection that failed boot reconciliation
    but remains visible for recovery. Available operations are denormalized
    from the catalog so list/resolve need no catalog lookup.

    Runtime-only fields:

    - ``state`` — ``"running"`` while the broker is up, flipped to
      ``"auth_failed"`` when the broker exits with code 77 (upstream
      rejected creds) and the watcher stops respawning, or ``"broken"``
      when the broker fails to come up three times in a row. Both terminal
      states can be recovered by reconnecting with replacement credentials.
    - ``expected_termination`` — set to ``True`` by the supervisor's
      remove flow before SIGTERM so the crash watcher knows this exit
      was on purpose and stays out of the respawn loop.
    """

    meta: ConnectionMeta
    # ``None`` is a persisted connection that could not start during boot
    # reconciliation. Keeping the record visible lets the UI reconnect or
    # remove it instead of orphaning its vault entry.
    broker: BrokerHandle | None
    available_operations: OperationGrants = frozenset()
    state: ConnectionState = "running"
    expected_termination: bool = False
    # Serialize grant handoffs with reconnect/remove and watcher respawns.
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class Registry:
    """Thin typed wrapper around a dict so callers don't reach into internals."""

    def __init__(self) -> None:
        self._by_id: dict[str, BrokeredConnectionRecord] = {}

    def add(self, record: BrokeredConnectionRecord) -> None:
        self._by_id[record.meta.id] = record

    def get(self, connection_id: str) -> BrokeredConnectionRecord | None:
        return self._by_id.get(connection_id)

    def remove(self, connection_id: str) -> BrokeredConnectionRecord | None:
        return self._by_id.pop(connection_id, None)

    def list(self) -> list[BrokeredConnectionRecord]:
        return list(self._by_id.values())

    def contains(self, connection_id: str) -> bool:
        return connection_id in self._by_id
