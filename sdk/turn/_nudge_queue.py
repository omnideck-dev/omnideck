"""Per-agent nudge queue storage.

Leaf module with no internal imports — both ``sdk.turn._turn`` and
``sdk.events._context`` can import from here without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class QueuedNudge:
    """One pending nudge that can be addressed before it is drained."""

    id: str
    message: str


# Keyed by agent ID (context_id from agent_span).
_nudge_queues: dict[str, list[QueuedNudge]] = {}


def register_nudge_queue(agent_id: str) -> None:
    """Create an empty nudge queue so *agent_id* can receive nudges."""
    _nudge_queues[agent_id] = []


def unregister_nudge_queue(agent_id: str) -> None:
    """Remove the nudge queue for *agent_id*."""
    _nudge_queues.pop(agent_id, None)


def queue_nudge(target_id: str, message: str) -> QueuedNudge | None:
    """Append a nudge message to the queue for *target_id*.

    Returns the addressable queue entry, or ``None`` when the target no
    longer has an active queue.
    """
    q = _nudge_queues.get(target_id)
    if q is not None:
        nudge = QueuedNudge(id=uuid4().hex, message=message)
        q.append(nudge)
        return nudge
    return None


def list_nudges(agent_id: str) -> list[QueuedNudge]:
    """Return a snapshot of pending nudges for *agent_id* in FIFO order."""
    return list(_nudge_queues.get(agent_id, ()))


def delete_nudge(agent_id: str, nudge_id: str) -> QueuedNudge | None:
    """Delete one pending nudge, returning it when it was still queued."""
    q = _nudge_queues.get(agent_id)
    if not q:
        return None
    for index, nudge in enumerate(q):
        if nudge.id == nudge_id:
            return q.pop(index)
    return None


def drain_nudges(agent_id: str | None = None) -> list[str]:
    """Pop and return all queued nudge messages for *agent_id*.

    Returns an empty list if the agent has no queue or no messages.
    """
    if agent_id is None:
        return []
    q = _nudge_queues.get(agent_id)
    if not q:
        return []
    messages = [nudge.message for nudge in q]
    q.clear()
    return messages
