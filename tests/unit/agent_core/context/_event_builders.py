"""Shared flat-event builders for the _view derivation tests.

These mirror the events.jsonl record shape (id / type / timestamp /
conversation_id / agent_id / depth + payload fields) so the view functions
can be exercised without standing up a real ConversationHistory.
"""

from __future__ import annotations

CONV = "c1"
ROOT = "root.computron.1"
SUB = "root.computron.1.research.2"


def _depth(agent_id: str) -> int:
    # agent_id encodes nesting: root.<profile>.<n> = depth 0, each
    # ".<name>.<n>" past that adds a level.
    return (len(agent_id.split(".")) - 1) // 2 - 1


def _started(agent_id: str, name: str, parent: str | None = None) -> dict:
    return {
        "id": f"evt_started_{agent_id}",
        "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00",
        "conversation_id": CONV,
        "agent_id": agent_id,
        "depth": _depth(agent_id),
        "agent_name": name,
        "parent_agent_id": parent,
    }


def _user(agent_id: str, content: str, evt_id: str = "evt_u", attachments=None) -> dict:
    return {
        "id": evt_id,
        "type": "user_message",
        "timestamp": "2026-01-01T00:00:01",
        "conversation_id": CONV,
        "agent_id": agent_id,
        "depth": _depth(agent_id),
        "content": content,
        "attachments": attachments or [],
    }


def _iter(agent_id: str, idx: int, content: str = "", thinking: str = "",
          tool_calls=None, evt_id: str = "evt_i") -> dict:
    return {
        "id": evt_id,
        "type": "iteration",
        "timestamp": f"2026-01-01T00:00:{10 + idx:02d}",
        "conversation_id": CONV,
        "agent_id": agent_id,
        "depth": _depth(agent_id),
        "iteration_index": idx,
        "content": content or None,
        "thinking": thinking or None,
        "tool_calls": tool_calls or [],
    }


def _tool(agent_id: str, tool_name: str, content: str, call_id: str | None = "c1",
          evt_id: str = "evt_t") -> dict:
    return {
        "id": evt_id,
        "type": "tool_result",
        "timestamp": "2026-01-01T00:00:20",
        "conversation_id": CONV,
        "agent_id": agent_id,
        "depth": _depth(agent_id),
        "tool_call_id": call_id,
        "tool_name": tool_name,
        "content": content,
    }


def _compaction(agent_id: str, summary: str, kept_from_id: str, kept_to_id: str,
                user_intent_summary: str | None = None, evt_id: str = "evt_c",
                ts: str = "2026-01-01T00:00:30") -> dict:
    return {
        "id": evt_id,
        "type": "compaction",
        "timestamp": ts,
        "conversation_id": CONV,
        "agent_id": agent_id,
        "depth": _depth(agent_id),
        "kept_from_id": kept_from_id,
        "kept_to_id": kept_to_id,
        "summary_text": summary,
        "user_intent_summary": user_intent_summary,
    }
