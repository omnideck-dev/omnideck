"""Tests for build_llm_history — the events.jsonl → LLM messages derivation."""

from __future__ import annotations

import pytest

from sdk.context._view import (
    _INTENT_PREFIX,
    _SUMMARY_PREFIX,
    build_llm_history,
)


CONV = "c1"
ROOT = "root.computron.1"
SUB = "root.computron.1.research.2"


def _started(agent_id: str, name: str, parent: str | None = None) -> dict:
    return {
        "id": f"evt_started_{agent_id}",
        "type": "agent_started",
        "timestamp": "2026-01-01T00:00:00",
        "conversation_id": CONV,
        "agent_id": agent_id,
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
        "kept_from_id": kept_from_id,
        "kept_to_id": kept_to_id,
        "summary_text": summary,
        "user_intent_summary": user_intent_summary,
        "audit": {"model": "m", "input_char_count": 0, "elapsed_seconds": 0.0},
    }


pytestmark = [pytest.mark.unit]


def test_empty_events_returns_empty():
    assert build_llm_history([], CONV) == []


def test_no_user_message_returns_empty():
    """Without a user_message, there's nothing to anchor the rebuild on."""
    events = [_started(ROOT, "COMPUTRON")]
    assert build_llm_history(events, CONV) == []


def test_simple_user_assistant_round():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "hi"),
        _iter(ROOT, 0, content="hello"),
    ]
    msgs = build_llm_history(events, CONV)
    assert msgs == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "agent_name": "COMPUTRON"},
    ]


def test_iteration_with_tool_call_and_result():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "run ls"),
        _iter(ROOT, 0, content="okay", tool_calls=[
            {"id": "c1", "name": "shell", "arguments": {"cmd": "ls"}},
        ]),
        _tool(ROOT, "shell", "a.txt\nb.txt", call_id="c1"),
        _iter(ROOT, 1, content="two files."),
    ]
    msgs = build_llm_history(events, CONV)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1]["tool_calls"] == [
        {"id": "c1", "function": {"name": "shell", "arguments": {"cmd": "ls"}}},
    ]
    assert msgs[2]["tool_call_id"] == "c1"
    assert msgs[2]["content"] == "a.txt\nb.txt"


def test_thinking_carries_through():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "go"),
        _iter(ROOT, 0, content="done", thinking="planning"),
    ]
    msgs = build_llm_history(events, CONV)
    assert msgs[1]["thinking"] == "planning"


def test_thinking_only_iteration_excluded_from_messages():
    """A thinking-only iteration (no content, no tool calls — e.g. a partial
    captured by a mid-stream stop) must not become an assistant message:
    OpenAI-style providers reject assistant messages without text or tool
    calls on the next turn."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "go"),
        _iter(ROOT, 0, thinking="planning"),
    ]
    msgs = build_llm_history(events, CONV)
    assert msgs == [{"role": "user", "content": "go"}]


def test_attachments_appended_to_first_user_message():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "look at this",
              attachments=[{"filename": "a.png", "content_type": "image/png", "path": "/v/a.png"}]),
        _iter(ROOT, 0, content="ok"),
    ]
    msgs = build_llm_history(events, CONV)
    assert "[Attached files written to virtual computer]" in msgs[0]["content"]
    assert "/v/a.png" in msgs[0]["content"]


def test_nudge_appears_as_second_user_message():
    """A second user_message mid-loop (a nudge) shows up in the kept range."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "start", evt_id="evt_u1"),
        _iter(ROOT, 0, content="working", evt_id="evt_i1"),
        _user(ROOT, "also mention X", evt_id="evt_u2"),  # the nudge
        _iter(ROOT, 1, content="done with X", evt_id="evt_i2"),
    ]
    msgs = build_llm_history(events, CONV)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[2]["content"] == "also mention X"


def test_root_view_excludes_subagent_events():
    """Root view (no agent_filter) skips events from sub-agents entirely."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "delegate this"),
        _iter(ROOT, 0, content="spawning"),
        _started(SUB, "RESEARCH", parent=ROOT),
        _user(SUB, "research X"),
        _iter(SUB, 0, content="result"),
        _iter(ROOT, 1, content="here is what the sub found"),
    ]
    root_msgs = build_llm_history(events, CONV)
    assert [m["role"] for m in root_msgs] == ["user", "assistant", "assistant"]
    assert "spawning" in (root_msgs[1].get("content") or "")
    assert "result" not in (root_msgs[1].get("content") or "")


def test_subagent_filter_returns_only_subagent_view():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "delegate"),
        _iter(ROOT, 0, content="spawning"),
        _started(SUB, "RESEARCH", parent=ROOT),
        _user(SUB, "research X"),
        _iter(SUB, 0, content="result"),
    ]
    sub_msgs = build_llm_history(events, CONV, agent_filter=SUB)
    assert sub_msgs == [
        {"role": "user", "content": "research X"},
        {"role": "assistant", "content": "result", "agent_name": "RESEARCH"},
    ]


def test_compaction_applies_summary_marker_and_kept_range():
    """The latest compaction inserts the summary marker and clips the
    history to events from kept_from_id forward."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "first user msg", evt_id="evt_u1"),
        _iter(ROOT, 0, content="working", evt_id="evt_i1"),
        _iter(ROOT, 1, content="still working", evt_id="evt_i2"),
        _iter(ROOT, 2, content="recent", evt_id="evt_i3"),  # kept_from here
        _compaction(ROOT, "summary text",
                    kept_from_id="evt_i3", kept_to_id="evt_i3"),
        _iter(ROOT, 3, content="after compaction", evt_id="evt_i4"),
    ]
    msgs = build_llm_history(events, CONV)
    assert [m["role"] for m in msgs] == ["user", "assistant", "assistant", "assistant"]
    assert msgs[0]["content"] == "first user msg"
    assert msgs[1]["content"].startswith(_SUMMARY_PREFIX)
    assert "summary text" in msgs[1]["content"]
    assert msgs[2]["content"] == "recent"
    assert msgs[3]["content"] == "after compaction"


def test_compaction_user_intent_summary_overrides_first_user_message():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "original ask", evt_id="evt_u1"),
        _iter(ROOT, 0, content="...", evt_id="evt_i1"),
        _iter(ROOT, 1, content="recent", evt_id="evt_i2"),
        _compaction(ROOT, "summary",
                    kept_from_id="evt_i2", kept_to_id="evt_i2",
                    user_intent_summary="user wants Z now"),
    ]
    msgs = build_llm_history(events, CONV)
    assert msgs[0]["content"] == _INTENT_PREFIX + "user wants Z now"


def test_only_latest_compaction_applied():
    """Older compactions stay in the log for audit but don't reshape
    the LLM view — only the most recent one matters."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "anchor", evt_id="evt_u1"),
        _iter(ROOT, 0, content="x", evt_id="evt_i1"),
        _compaction(ROOT, "OLD SUMMARY",
                    kept_from_id="evt_i1", kept_to_id="evt_i1",
                    evt_id="evt_c1", ts="2026-01-01T00:00:30"),
        _iter(ROOT, 1, content="y", evt_id="evt_i2"),
        _compaction(ROOT, "NEW SUMMARY",
                    kept_from_id="evt_i2", kept_to_id="evt_i2",
                    evt_id="evt_c2", ts="2026-01-01T00:01:00"),
        _iter(ROOT, 2, content="after", evt_id="evt_i3"),
    ]
    msgs = build_llm_history(events, CONV)
    summary_msg = msgs[1]
    assert "NEW SUMMARY" in summary_msg["content"]
    assert "OLD SUMMARY" not in summary_msg["content"]


def test_subagent_compaction_excluded_from_root_view():
    """A compaction emitted by a sub-agent doesn't affect the root view —
    the root filter strips it just like any other sub-agent event."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "delegate"),
        _iter(ROOT, 0, content="spawn"),
        _started(SUB, "RESEARCH", parent=ROOT),
        _user(SUB, "do research"),
        _iter(SUB, 0, content="...", evt_id="evt_si1"),
        _iter(SUB, 1, content="recent", evt_id="evt_si2"),
        _compaction(SUB, "sub summary",
                    kept_from_id="evt_si2", kept_to_id="evt_si2"),
        _iter(ROOT, 1, content="root continues"),
    ]
    root_msgs = build_llm_history(events, CONV)
    # Root view: no summary marker, no sub events.
    assert not any(_SUMMARY_PREFIX in (m.get("content") or "") for m in root_msgs)
    assert [m["role"] for m in root_msgs] == ["user", "assistant", "assistant"]


def test_other_conversations_filtered_out():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "mine"),
        _iter(ROOT, 0, content="ok"),
        # Same shape but a different conversation:
        {**_started(ROOT, "OTHER"), "conversation_id": "c2"},
        {**_user(ROOT, "theirs", evt_id="evt_u2"), "conversation_id": "c2"},
    ]
    msgs = build_llm_history(events, CONV)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "mine"


# ── apply_compactions=False (chat view) preserves the user's typed text ──


def test_chat_view_does_not_augment_first_user_message_with_attachments():
    """The augmented `[Attached files written to virtual computer]` block
    is for the LLM; the chat view shows what the user actually typed."""
    user_evt = _user(ROOT, "look at this")
    user_evt["attachments"] = [{
        "filename": "a.txt", "content_type": "text/plain",
        "path": "/home/computron/uploads/a.txt",
    }]
    events = [_started(ROOT, "COMPUTRON"), user_evt]
    msgs = build_llm_history(events, CONV, apply_compactions=False)
    assert msgs[0]["content"] == "look at this"
    assert "Attached files" not in msgs[0]["content"]


def test_llm_view_does_augment_first_user_message_with_attachments():
    """The LLM view (apply_compactions=True) appends the attachment block
    so the model can find the uploaded files in the sandbox."""
    user_evt = _user(ROOT, "look at this")
    user_evt["attachments"] = [{
        "filename": "a.txt", "content_type": "text/plain",
        "path": "/home/computron/uploads/a.txt",
    }]
    events = [_started(ROOT, "COMPUTRON"), user_evt]
    msgs = build_llm_history(events, CONV, apply_compactions=True)
    assert "Attached files" in msgs[0]["content"]
    assert "/home/computron/uploads/a.txt" in msgs[0]["content"]
