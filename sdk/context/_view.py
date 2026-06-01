"""Build an LLM message list from an events.jsonl-shaped event sequence.

Pure function over a list of flat event dicts (the same shape persisted
to events.jsonl). No I/O. Used by ConversationHistory to derive its
`messages` view, and by future migration tooling to validate parity.

Algorithm:
1. Filter to events for the requested conversation.
2. Filter to the requested agent's view:
   - root view: events from any depth-0 agent (parent_agent_id is None);
   - per-agent view: events for that specific agent_id, including its
     own compactions.
3. Find the latest compaction event (max timestamp). Older compactions
   stay in the log for audit; only the latest affects the LLM view.
4. Emit the first user message, applying `user_intent_summary` from the
   latest compaction if present.
5. If a compaction exists, emit its summary marker, then walk events
   from `kept_from_id` forward (skipping any older compaction events).
6. Otherwise, walk all events after the first user message.

The emitted message dicts mirror the shape of today's history.json.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The exact text the LLM sees as a prefix on the compacted summary message.
# Kept verbatim from today's strategy so summarizer-eval comparisons hold.
_SUMMARY_PREFIX = "[Conversation summary — earlier messages were compacted]\n\n"

# Prefix applied to the first user message when a compaction carries a
# `user_intent_summary` (consolidated user intent from multiple user
# messages). Kept verbatim from today's strategy.
_INTENT_PREFIX = "[User intent history]\n"


def build_llm_history(
    events: list[dict[str, Any]],
    conversation_id: str,
    agent_filter: str | None = None,
    *,
    apply_compactions: bool = True,
) -> list[dict[str, Any]]:
    """Reconstruct the LLM message list for an agent from event records.

    Args:
        events: Flat event dicts (the events.jsonl shape — id, type,
            timestamp, conversation_id, agent_id, plus payload fields).
        conversation_id: Restrict to events for this conversation.
        agent_filter: If provided, return that agent's view. If None,
            return the root view (events from any depth-0 agent).
        apply_compactions: When True (default), the latest compaction
            event collapses the conversation into pin + summary marker
            + kept tail — the LLM view. When False, return the original
            sequence of user/assistant/tool messages with no collapsing —
            the user-facing view for chat rendering.

    Returns:
        A list of message dicts ready to send to a provider, in the
        same shape as today's history.json.
    """
    conv_events = [e for e in events if e.get("conversation_id") == conversation_id]

    if agent_filter:
        evs = [e for e in conv_events if e.get("agent_id") == agent_filter]
    else:
        root_ids = {
            e["agent_id"] for e in conv_events
            if e["type"] == "agent_started" and not e.get("parent_agent_id")
        }
        evs = [e for e in conv_events if e.get("agent_id") in root_ids]

    agent_names = {
        e["agent_id"]: e.get("agent_name")
        for e in events if e["type"] == "agent_started"
    }

    first_user = next((e for e in evs if e["type"] == "user_message"), None)
    if first_user is None:
        return []

    latest_compaction = max(
        (e for e in evs if e["type"] == "compaction"),
        key=lambda c: c["timestamp"],
        default=None,
    ) if apply_compactions else None

    # First user message, with intent summary override if a compaction set it.
    # The attachment block (`[Attached files written to virtual computer]…`)
    # is an LLM-facing transformation — it tells the model where to find
    # the uploaded files in the sandbox. The chat view (apply_compactions
    # =False) shows what the user actually typed, so we skip that
    # augmentation there.
    user_content = first_user["content"]
    if latest_compaction and latest_compaction.get("user_intent_summary"):
        user_content = _INTENT_PREFIX + latest_compaction["user_intent_summary"]
    elif first_user.get("attachments") and apply_compactions:
        user_content = _augment_with_attachments(user_content, first_user["attachments"])
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

    first_user_idx = evs.index(first_user)
    if latest_compaction is None:
        start_idx = first_user_idx + 1
    else:
        messages.append({
            "role": "assistant",
            "content": _SUMMARY_PREFIX + latest_compaction["summary_text"],
        })
        try:
            start_idx = next(
                i for i, e in enumerate(evs)
                if e["id"] == latest_compaction["kept_from_id"]
            )
        except StopIteration:
            return messages

    for e in evs[start_idx:]:
        t = e["type"]
        if t == "compaction":
            continue
        if t == "user_message":
            content = e["content"]
            if e.get("attachments") and apply_compactions:
                content = _augment_with_attachments(content, e["attachments"])
            messages.append({"role": "user", "content": content})
        elif t == "iteration":
            msg: dict[str, Any] = {"role": "assistant"}
            if e.get("thinking"):
                msg["thinking"] = e["thinking"]
            if e.get("content"):
                msg["content"] = e["content"]
            tool_calls = e.get("tool_calls") or []
            if tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id"),
                        "function": {"name": tc["name"], "arguments": tc.get("arguments")},
                    }
                    for tc in tool_calls
                ]
            name = agent_names.get(e["agent_id"])
            if name:
                msg["agent_name"] = name
            messages.append(msg)
        elif t == "tool_result":
            messages.append({
                "role": "tool",
                "tool_call_id": e.get("tool_call_id"),
                "tool_name": e.get("tool_name"),
                "content": e["content"],
            })
    return messages


def _augment_with_attachments(content: str, attachments: list[dict[str, Any]]) -> str:
    """Append the [Attached files…] block the LLM sees for an upload."""
    lines = [
        f"  - {a['filename']} ({a['content_type']}) -> {a['path']}"
        for a in attachments
    ]
    return f"{content}\n\n[Attached files written to virtual computer]\n" + "\n".join(lines)


# Rough chars-per-token estimate. The exact ratio varies by tokenizer
# but ~4 chars/token is a stable approximation for English.
_CHARS_PER_TOKEN = 4


def _approx_tokens(chars: int) -> int:
    return chars // _CHARS_PER_TOKEN


def _parse_iso(ts: str) -> float | None:
    """Return a POSIX timestamp for an ISO-8601 string, or None on failure."""
    if not ts:
        return None
    try:
        from datetime import datetime
        # ``fromisoformat`` accepts both "+00:00" and naive forms.
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None


__all__ = ["build_llm_history"]
