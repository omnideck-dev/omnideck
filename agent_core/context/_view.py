"""Derive an agent's message list from an events.jsonl-shaped event sequence.

Two pure views over the same flat event dicts (the shape persisted to
events.jsonl), no I/O:

- ``build_llm_view`` — the model-facing list: collapsed at the latest
  compaction (first user message + summary marker + kept tail), with user
  messages augmented with the [Attached files…] block the model needs to
  locate uploads. This is what the provider is prompted with.
- ``build_transcript_view`` — the user-facing list: the conversation as it
  happened — no compaction collapse, user text verbatim. This is what the
  frontend renders (it interleaves compaction chips itself).

Both filter to one agent's thread via ``events_for_agent`` and emit message
dicts in the same shape as today's history.json. The caller passes a single
conversation's events.
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


def events_for_agent(
    events: list[dict[str, Any]],
    agent_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return the events that make up one agent's conversation thread.

    The caller passes a single conversation's events (one events.jsonl).
    This is the single definition of "which events are mine":

    - per-agent view (``agent_filter`` set): events for that exact
      ``agent_id``;
    - root view (``agent_filter`` is None): every depth-0 event
      (``depth == 0``). This spans every root turn regardless of the
      per-turn ``.N`` agent_id suffix or which profile produced the turn —
      so it stays stable across a mid-conversation profile switch.

    Both the derived message views and compaction's kept-bounds resolution
    read membership from here so they cannot drift apart.
    """
    if agent_filter:
        return [e for e in events if e.get("agent_id") == agent_filter]
    return [e for e in events if e.get("depth") == 0]


def build_llm_view(
    events: list[dict[str, Any]],
    agent_filter: str | None = None,
) -> list[dict[str, Any]]:
    """The model-facing message list for one agent.

    Collapses the conversation at its latest compaction (first user message
    + summary marker + the kept tail) and augments user messages with the
    [Attached files…] block, so the model knows where uploads landed in the
    sandbox. This is the list sent to the provider.
    """
    evs = events_for_agent(events, agent_filter)
    first_user = next((e for e in evs if e["type"] == "user_message"), None)
    if first_user is None:
        return []
    agent_names = _agent_names(events)

    latest_compaction = max(
        (e for e in evs if e["type"] == "compaction"),
        key=lambda c: c["timestamp"],
        default=None,
    )

    # First user message: intent-summary override if a compaction set one,
    # else the user's text with the attachment block appended.
    if latest_compaction and latest_compaction.get("user_intent_summary"):
        user_content = _INTENT_PREFIX + latest_compaction["user_intent_summary"]
    elif first_user.get("attachments"):
        user_content = _augment_with_attachments(
            first_user["content"], first_user["attachments"],
        )
    else:
        user_content = first_user["content"]
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

    if latest_compaction is None:
        start_idx = evs.index(first_user) + 1
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

    messages.extend(_walk(evs[start_idx:], agent_names, augment=True))
    return messages


def build_transcript_view(
    events: list[dict[str, Any]],
    agent_filter: str | None = None,
) -> list[dict[str, Any]]:
    """The user-facing message list for one agent.

    The conversation as it actually happened — no compaction collapse, and
    the user's messages verbatim (no [Attached files…] augmentation). The
    frontend renders this and draws compaction chips at their points.
    """
    evs = events_for_agent(events, agent_filter)
    first_user = next((e for e in evs if e["type"] == "user_message"), None)
    if first_user is None:
        return []
    agent_names = _agent_names(events)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": first_user["content"]},
    ]
    tail = evs[evs.index(first_user) + 1:]
    messages.extend(_walk(tail, agent_names, augment=False))
    return messages


def _agent_names(events: list[dict[str, Any]]) -> dict[str, str | None]:
    """Map agent_id → agent_name from the agent_started events."""
    return {
        e["agent_id"]: e.get("agent_name")
        for e in events if e["type"] == "agent_started"
    }


def _walk(
    evs: list[dict[str, Any]],
    agent_names: dict[str, str | None],
    *,
    augment: bool,
) -> list[dict[str, Any]]:
    """Emit user/assistant/tool messages for a slice of events.

    ``augment``: append the [Attached files…] block to user messages — an
    LLM-facing transformation that tells the model where uploads landed.
    The transcript view passes False to show what the user actually typed.
    """
    out: list[dict[str, Any]] = []
    for e in evs:
        t = e["type"]
        if t == "compaction":
            continue
        if t == "user_message":
            content = e["content"]
            if e.get("attachments") and augment:
                content = _augment_with_attachments(content, e["attachments"])
            out.append({"role": "user", "content": content})
        elif t == "iteration":
            # An assistant message with neither content nor tool calls (e.g.
            # a thinking-only partial captured when the user stopped
            # mid-stream) is not valid provider-facing history — OpenAI-style
            # APIs require text or tool calls on assistant messages. The
            # event stays in the log for the UI; the model never sees it.
            if not e.get("content") and not (e.get("tool_calls") or []):
                continue
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
            out.append(msg)
        elif t == "tool_result":
            out.append({
                "role": "tool",
                "tool_call_id": e.get("tool_call_id"),
                "tool_name": e.get("tool_name"),
                "content": e["content"],
            })
    return out


def _augment_with_attachments(content: str, attachments: list[dict[str, Any]]) -> str:
    """Append the [Attached files…] block the LLM sees for an upload."""
    lines = [
        f"  - {a['filename']} ({a['content_type']}) -> {a['path']}"
        for a in attachments
    ]
    return f"{content}\n\n[Attached files written to virtual computer]\n" + "\n".join(lines)


__all__ = ["build_llm_view", "build_transcript_view", "events_for_agent"]
