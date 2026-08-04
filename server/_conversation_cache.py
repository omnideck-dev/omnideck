"""In-memory conversation cache and resume support."""

import logging
from collections import OrderedDict
from typing import Any

from conversations import (
    load_browser_tabs,
    load_conversation_profile,
    load_events_jsonl,
    load_preview_state,
    load_terminal,
)
from sdk.context import ConversationHistory
from sdk.context._view import build_transcript_view
from sdk.events import run_conversation_exit_hooks
from sdk.turn import is_turn_active

logger = logging.getLogger(__name__)


# In-memory conversation cache. LRU-bounded so a long-lived process
# doesn't hold every conversation a user has ever opened. The on-disk
# state is authoritative; an evicted entry is rehydrated from disk on
# next access.
_MAX_CACHED_CONVERSATIONS = 25
_conversations: OrderedDict[str, ConversationHistory] = OrderedDict()


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

    ``exclude`` skips the conversation that triggered this eviction. The
    caller has not yet entered ``turn_scope`` for it, so ``is_turn_active``
    cannot recognize it as protected — without this guard the just-inserted
    entry would be evicted by its own insert in the rare case where every
    other cached entry is mid-turn.
    """
    while len(_conversations) > _MAX_CACHED_CONVERSATIONS:
        for cid in _conversations:
            if cid == exclude:
                continue
            if not is_turn_active(cid):
                _conversations.pop(cid)
                await run_conversation_exit_hooks(cid)
                logger.info(
                    "Evicted LRU conversation %s from in-memory cache", cid,
                )
                break
        else:
            # Every cached conversation is mid-turn (or is the just-inserted
            # caller) — accept temporary overflow rather than evict an
            # active one. The next insert will retry.
            return


async def resume_conversation(
    conversation_id: str,
    *,
    allow_empty: bool = False,
) -> dict | None:
    """Load a conversation's history derived from events.jsonl.

    Returns a dict with:
        messages: the conversation transcript derived from the event log
            via ``build_transcript_view`` (user-facing, not the compacted
            LLM view).
        events: complete persisted canonical event log. The frontend decides
            which state models each event contributes to; this API does not
            maintain a second event-type allowlist.
        browser_tabs: latest browser snapshot per tab from the sidecar,
            so the preview panel restores without replaying screenshots.
        terminal: per-agent terminal transcripts from the sidecar (the
            last N commands, merged), keyed by agent_id.
        preview_state: persisted preview-panel state.
        profile_id: the agent profile last used in this conversation, or
            None if it predates per-conversation profiles.

    Args:
        conversation_id: Conversation whose persisted state should be loaded.
        allow_empty: Return an empty snapshot when no event has reached disk
            yet. The resume route uses this only when a manager-owned run proves
            the conversation currently exists.

    Returns None when no events are present and ``allow_empty`` is false —
    conversations created before the events-first cutover have no replay source
    and cannot otherwise be opened.
    """
    # Disk is the durability contract for resume. The in-memory history keeps
    # only what the active LLM view needs and is deliberately not a second
    # persistence policy.
    events = load_events_jsonl(conversation_id)
    if not events and not allow_empty:
        return None

    if conversation_id in _conversations:
        _conversations.move_to_end(conversation_id)
    else:
        await _hydrate(conversation_id, events)

    # Transcript view: the conversation as it happened, not the
    # post-compaction LLM view. The frontend draws compaction chips itself.
    transcript = build_transcript_view(events)
    return {
        "messages": transcript,
        "events": events,
        "browser_tabs": load_browser_tabs(conversation_id),
        "terminal": load_terminal(conversation_id),
        "preview_state": load_preview_state(conversation_id),
        "profile_id": load_conversation_profile(conversation_id),
    }
