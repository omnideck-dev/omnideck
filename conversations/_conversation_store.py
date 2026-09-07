"""Instance-owned conversation histories, leases, and asynchronous resources."""

from __future__ import annotations

import asyncio
from collections import Counter, OrderedDict
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from agent_core.context import ConversationHistory, build_transcript_view

from ._browser_tabs import load_browser_tabs
from ._events_log import load_events_jsonl
from ._models import ConversationResumeState
from ._store import load_conversation_profile, load_preview_state
from ._terminal import load_terminal


@dataclass
class ConversationScope:
    """A conversation's working history and resources, shared across its runs."""

    history: ConversationHistory
    resources: AsyncExitStack = field(default_factory=AsyncExitStack)
    transient: bool = False


class ConversationStore:
    """Retain interactive conversations and release resources at their lifetime boundary.

    Resource owners attach cleanup to a scope. The store knows nothing about
    browsers or other concrete resource types. Disk remains authoritative for resume.
    """

    def __init__(self, *, max_cached: int = 25) -> None:
        if max_cached < 1:
            raise ValueError("max_cached must be positive")
        self._max_cached = max_cached
        self._conversations: OrderedDict[str, ConversationScope] = OrderedDict()
        self._leases: Counter[str] = Counter()
        self._lock = asyncio.Lock()
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Conversation store is closed")

    async def _load_history(self, conversation_id: str) -> ConversationHistory:
        history = ConversationHistory(conversation_id=conversation_id)
        history.seed_events(load_events_jsonl(conversation_id))
        return history

    async def _get_locked(
        self, conversation_id: str, *, events: list[dict[str, Any]] | None = None, transient: bool = False,
    ) -> ConversationScope:
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if conversation_id in self._conversations:
            self._conversations.move_to_end(conversation_id)
            return self._conversations[conversation_id]
        if transient or events is not None:
            history = ConversationHistory(conversation_id=conversation_id)
            if events is not None:
                history.seed_events(events)
        else:
            history = await self._load_history(conversation_id)
        scope = ConversationScope(history)
        self._conversations[conversation_id] = scope
        await self._evict_lru(exclude=conversation_id)
        return scope

    async def get_or_create_conversation(self, conversation_id: str) -> ConversationHistory:
        """Return a warm history or hydrate it from persisted events."""
        async with self._lock:
            self._check_open()
            return (await self._get_locked(conversation_id)).history

    @asynccontextmanager
    async def acquire(self, conversation_id: str, *, transient: bool = False) -> AsyncIterator[ConversationScope]:
        """Lease a conversation; transient scopes close when their run releases them."""
        async with self._lock:
            self._check_open()
            self._leases[conversation_id] += 1
            try:
                scope = await self._get_locked(conversation_id, transient=transient)
                scope.transient = scope.transient or transient
            except BaseException:
                self._release_lease(conversation_id)
                raise
        try:
            yield scope
        finally:
            # Cancellation while waiting for another conversation's eviction
            # must not abandon this lease or its transient resource cleanup.
            cleanup = asyncio.create_task(self._release(conversation_id, scope))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _release(self, conversation_id: str, scope: ConversationScope) -> None:
        async with self._lock:
            self._release_lease(conversation_id)
            if scope.transient and not self._leases[conversation_id]:
                await self._evict(conversation_id)

    def _release_lease(self, conversation_id: str) -> None:
        self._leases[conversation_id] -= 1
        if not self._leases[conversation_id]:
            del self._leases[conversation_id]

    async def evict_conversation(self, conversation_id: str) -> bool:
        """Remove an idle conversation and await all of its resource cleanup."""
        async with self._lock:
            if self._leases[conversation_id]:
                raise RuntimeError("Cannot evict a leased conversation")
            return await self._evict(conversation_id)

    async def _evict(self, conversation_id: str) -> bool:
        scope = self._conversations.pop(conversation_id, None)
        if scope is None:
            return False
        await scope.resources.aclose()
        return True

    async def _evict_lru(self, *, exclude: str) -> None:
        while len(self._conversations) > self._max_cached:
            candidate = next((cid for cid in self._conversations if cid != exclude and not self._leases[cid]), None)
            if candidate is None:
                return  # Temporary overflow while every other conversation is leased.
            await self._evict(candidate)

    async def close(self) -> None:
        """Close every retained scope after all run owners have released leases."""
        async with self._lock:
            if self._leases:
                raise RuntimeError("Cannot close a conversation store with active leases")
            self._closed = True
            scopes = tuple(self._conversations.values())
            self._conversations.clear()
            async with AsyncExitStack() as cleanup:
                for scope in scopes:
                    cleanup.push_async_callback(scope.resources.aclose)

    async def load_conversation_resume_state(
        self, conversation_id: str,
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

        async with self._lock:
            self._check_open()
            await self._get_locked(conversation_id, events=events)

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
