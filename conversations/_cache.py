"""In-memory conversation cache and persisted resume state."""

import logging
from collections import Counter, OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agent_core.context import ConversationHistory
from agent_core.context import build_transcript_view

from ._browser_tabs import load_browser_tabs
from ._events_log import load_events_jsonl
from ._lifecycle import run_conversation_exit_hooks
from ._models import ConversationResumeState
from ._store import load_conversation_profile, load_preview_state
from ._terminal import load_terminal

logger = logging.getLogger(__name__)


# In-memory conversation cache. LRU-bounded so a long-lived process
# doesn't hold every conversation a user has ever opened. The on-disk
# state is authoritative; an evicted entry is rehydrated from disk on
# next access.
_leases: Counter[str] = Counter()


@contextmanager
def conversation_lease(conversation_id: str) -> Iterator[None]:
    """Keep cached conversation resources alive while an application run owns them."""
    _leases[conversation_id] += 1
    try:
        yield
    finally:
        _leases[conversation_id] -= 1
        if _leases[conversation_id] == 0:
            del _leases[conversation_id]


_MAX_CACHED_CONVERSATIONS = 25
_conversations: OrderedDict[str, ConversationHistory] = OrderedDict()


async def evict_conversation(conversation_id: str) -> bool:
    """Remove a conversation from memory and release its runtime resources."""
    removed = _conversations.pop(conversation_id, None) is not None
    await run_conversation_exit_hooks(conversation_id)
    return removed


async def _hydrate(conversation_id: str, events: list[dict[str, Any]]) -> ConversationHistory:
    """Build a history from *events*, cache it, and evict down to the cap."""
    history = ConversationHistory(conversation_id=conversation_id)
    history.seed_events(events)
    _conversations[conversation_id] = history
    await _evict_lru_conversation(exclude=conversation_id)
    return history


async def get_or_create_conversation(conversation_id: str) -> ConversationHistory:
    """Return cached history or restore it from persisted events.

    Cache hits move the entry to the end of the LRU; cache misses insert
    at the end and may evict the least-recently-used entry whose turn is
    not currently active.
    """
    if not conversation_id:
        msg = "conversation_id is required"
        raise ValueError(msg)
    if conversation_id in _conversations:
        _conversations.move_to_end(conversation_id)
        return _conversations[conversation_id]
    events = load_events_jsonl(conversation_id)
    if not events:
        logger.info("Creating new conversation %s", conversation_id)
    return await _hydrate(conversation_id, events)


async def _evict_lru_conversation(exclude: str | None = None) -> None:
    """Drop the oldest non-active entries until we are at or below the cap.

    Conversations whose turn is currently in flight are skipped — popping
    them from the dict would leave the running turn writing to a referent
    nobody else can find, and a subsequent chat for the same id would
    rehydrate from disk, producing two parallel writers.

    ``exclude`` also protects a newly hydrated conversation that is being
    opened for browsing without an active execution lease.
    """
    while len(_conversations) > _MAX_CACHED_CONVERSATIONS:
        for cid in _conversations:
            if cid == exclude:
                continue
            if not _leases[cid]:
                await evict_conversation(cid)
                logger.info(
                    "Evicted LRU conversation %s from in-memory cache",
                    cid,
                )
                break
        else:
            # Every cached conversation is mid-turn (or is the just-inserted
            # caller) — accept temporary overflow rather than evict an
            # active one. The next insert will retry.
            return


async def load_conversation_resume_state(
    conversation_id: str,
) -> ConversationResumeState:
    """Load the persisted state needed to resume a conversation.

    Args:
        conversation_id: Conversation whose persisted state should be loaded.

    Returns:
        Typed transcript, event, workspace, and agent-profile state.
    """
    # Disk is the durability contract for resume. The in-memory history keeps
    # only what the active LLM view needs and is deliberately not a second
    # persistence policy.
    events = load_events_jsonl(conversation_id)

    if conversation_id in _conversations:
        _conversations.move_to_end(conversation_id)
    else:
        await _hydrate(conversation_id, events)

    # Transcript view: the conversation as it happened, not the
    # post-compaction LLM view. The frontend draws compaction chips itself.
    transcript = build_transcript_view(events)
    return ConversationResumeState(
        messages=transcript,
        events=events,
        browser_tabs=load_browser_tabs(conversation_id),
        terminal=load_terminal(conversation_id),
        preview_state=load_preview_state(conversation_id),
        profile_id=load_conversation_profile(conversation_id),
    )
