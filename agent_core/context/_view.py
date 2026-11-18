"""Derive model-facing messages from a conversation's recorded events."""

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

APP_TEXT_PREFIX = "[System notice]"


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


def _opens_view(event: dict[str, Any]) -> bool:
    return event["type"] == "user_message" or bool(event.get("model_text"))


def pinned_message(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The user message kept at the top of the view across compactions.

    Only a typed message can be pinned, and only when it opens the thread.
    Text the app wrote is never pinned.
    """
    first = next((e for e in events if _opens_view(e)), None)
    return first if first is not None and first["type"] == "user_message" else None


def build_llm_view(
    events: list[dict[str, Any]],
    agent_filter: str | None = None,
) -> list[dict[str, Any]]:
    """The model-facing message list for one agent.

    Collapses the conversation at its latest compaction: the pinned first
    user message, if any, the summary, then the kept tail. Without a pinned
    message the summary opens the view as a user message, since providers
    need a user message first. This is the list sent to the provider.
    """
    evs = events_for_agent(events, agent_filter)
    first = next((e for e in evs if _opens_view(e)), None)
    if first is None:
        return []
    agent_names = _agent_names(events)
    pinned = pinned_message(evs)

    latest_compaction = max(
        (e for e in evs if e["type"] == "compaction"),
        key=lambda c: c["timestamp"],
        default=None,
    )

    if latest_compaction is None:
        return _walk(evs[evs.index(first):], agent_names)

    messages: list[dict[str, Any]] = []
    summary = _SUMMARY_PREFIX + latest_compaction["summary_text"]
    if pinned is not None:
        if latest_compaction.get("user_intent_summary"):
            user_content = _INTENT_PREFIX + latest_compaction["user_intent_summary"]
        else:
            user_content = _user_message_content(pinned)
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": summary})
    else:
        messages.append({"role": "user", "content": summary})
    try:
        start_idx = next(
            i for i, e in enumerate(evs)
            if e["id"] == latest_compaction["kept_from_id"]
        )
    except StopIteration:
        return messages

    messages.extend(_walk(evs[start_idx:], agent_names))
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
) -> list[dict[str, Any]]:
    """Emit model-facing user, assistant, and tool messages."""
    out: list[dict[str, Any]] = []
    for e in evs:
        t = e["type"]
        if t == "compaction":
            continue
        if t == "user_message":
            out.append({"role": "user", "content": _user_message_content(e)})
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
        elif e.get("model_text"):
            out.append({"role": "user", "content": f"{APP_TEXT_PREFIX}\n{e['model_text']}"})
    return out


def _user_message_content(event: dict[str, Any]) -> str:
    """The text the model reads for a user message, with any attachments listed."""
    content = event.get("model_text") or event["content"]
    if event.get("attachments"):
        content = _augment_with_attachments(content, event["attachments"])
    return content


def _augment_with_attachments(content: str, attachments: list[dict[str, Any]]) -> str:
    """Append the [Attached files…] block the LLM sees for an upload."""
    lines = [
        f"  - {a['filename']} ({a['content_type']}) -> {a['path']}"
        for a in attachments
    ]
    return f"{content}\n\n[Attached files written to virtual computer]\n" + "\n".join(lines)


__all__ = ["APP_TEXT_PREFIX", "build_llm_view", "events_for_agent", "pinned_message"]
