"""Tests for build_llm_view — the model-facing events.jsonl → messages view.

Covers the LLM derivation: assistant/tool walking, thinking, the
thinking-only exclusion, attachment augmentation, compaction collapse, and
root/sub-agent membership (events_for_agent) as exercised through this view.
"""

from __future__ import annotations

import pytest

from sdk.context._view import _INTENT_PREFIX, _SUMMARY_PREFIX, build_llm_view
from tests.unit.sdk.context._event_builders import (
    ROOT,
    SUB,
    _compaction,
    _iter,
    _started,
    _tool,
    _user,
)

pytestmark = [pytest.mark.unit]


def test_empty_events_returns_empty():
    assert build_llm_view([]) == []


def test_no_user_message_returns_empty():
    """Without a user_message, there's nothing to anchor the rebuild on."""
    events = [_started(ROOT, "COMPUTRON")]
    assert build_llm_view(events) == []


def test_simple_user_assistant_round():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "hi"),
        _iter(ROOT, 0, content="hello"),
    ]
    assert build_llm_view(events) == [
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
    assert build_llm_view(events) == [
        {"role": "user", "content": "run ls"},
        {
            "role": "assistant",
            "content": "okay",
            "tool_calls": [
                {"id": "c1", "function": {"name": "shell", "arguments": {"cmd": "ls"}}},
            ],
            "agent_name": "COMPUTRON",
        },
        {"role": "tool", "tool_call_id": "c1", "tool_name": "shell", "content": "a.txt\nb.txt"},
        {"role": "assistant", "content": "two files.", "agent_name": "COMPUTRON"},
    ]


def test_thinking_carries_through():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "go"),
        _iter(ROOT, 0, content="done", thinking="planning"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content": "go"},
        {"role": "assistant", "thinking": "planning", "content": "done", "agent_name": "COMPUTRON"},
    ]


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
    assert build_llm_view(events) == [{"role": "user", "content": "go"}]


def test_attachments_appended_to_first_user_message():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "look at this",
              attachments=[{"filename": "a.png", "content_type": "image/png", "path": "/v/a.png"}]),
        _iter(ROOT, 0, content="ok"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content":
            "look at this\n\n[Attached files written to virtual computer]\n"
            "  - a.png (image/png) -> /v/a.png"},
        {"role": "assistant", "content": "ok", "agent_name": "COMPUTRON"},
    ]


def test_nudge_appears_as_second_user_message():
    """A second user_message mid-loop (a nudge) shows up in the kept range."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "start", evt_id="evt_u1"),
        _iter(ROOT, 0, content="working", evt_id="evt_i1"),
        _user(ROOT, "also mention X", evt_id="evt_u2"),  # the nudge
        _iter(ROOT, 1, content="done with X", evt_id="evt_i2"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content": "start"},
        {"role": "assistant", "content": "working", "agent_name": "COMPUTRON"},
        {"role": "user", "content": "also mention X"},
        {"role": "assistant", "content": "done with X", "agent_name": "COMPUTRON"},
    ]


def test_root_view_excludes_subagent_events():
    """Root view skips a sub-agent's own thread but keeps the root's spawn round.

    A real delegation is a spawn_agent tool call on the root + a tool_result
    carrying the sub-agent's returned summary; the sub-agent runs its own
    (depth-1) thread in between. The root view keeps the call/result pair and
    drops the sub-agent's internal events.
    """
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "delegate this"),
        _iter(ROOT, 0, content="spawning a researcher", evt_id="evt_ri1", tool_calls=[
            {"id": "s1", "name": "spawn_agent", "arguments": {"profile": "research"}},
        ]),
        _started(SUB, "RESEARCH", parent=ROOT),
        _user(SUB, "research X", evt_id="evt_su"),
        _iter(SUB, 0, content="result", evt_id="evt_si"),
        _tool(ROOT, "spawn_agent", "the sub found 3 sources", call_id="s1", evt_id="evt_rt1"),
        _iter(ROOT, 1, content="here is what the sub found", evt_id="evt_ri2"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content": "delegate this"},
        {
            "role": "assistant",
            "content": "spawning a researcher",
            "tool_calls": [
                {"id": "s1", "function": {"name": "spawn_agent", "arguments": {"profile": "research"}}},
            ],
            "agent_name": "COMPUTRON",
        },
        {"role": "tool", "tool_call_id": "s1", "tool_name": "spawn_agent", "content": "the sub found 3 sources"},
        {"role": "assistant", "content": "here is what the sub found", "agent_name": "COMPUTRON"},
    ]


def test_subagent_filter_returns_only_subagent_view():
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "delegate"),
        _iter(ROOT, 0, content="spawning"),
        _started(SUB, "RESEARCH", parent=ROOT),
        _user(SUB, "research X"),
        _iter(SUB, 0, content="result"),
    ]
    assert build_llm_view(events, agent_filter=SUB) == [
        {"role": "user", "content": "research X"},
        {"role": "assistant", "content": "result", "agent_name": "RESEARCH"},
    ]


def test_root_view_spans_multiple_root_turns():
    """Each root turn gets its own agent_id (root.<profile>.N); the root view
    (depth 0) includes all of them, so the conversation survives across turns
    and profile switches."""
    root2 = "root.computron.2"
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "turn one", evt_id="evt_u1"),
        _iter(ROOT, 0, content="reply one", evt_id="evt_i1"),
        _started(root2, "COMPUTRON"),
        _user(root2, "turn two", evt_id="evt_u2"),
        _iter(root2, 0, content="reply two", evt_id="evt_i2"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content": "turn one"},
        {"role": "assistant", "content": "reply one", "agent_name": "COMPUTRON"},
        {"role": "user", "content": "turn two"},
        {"role": "assistant", "content": "reply two", "agent_name": "COMPUTRON"},
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
    assert build_llm_view(events) == [
        {"role": "user", "content": "first user msg"},
        {"role": "assistant", "content": _SUMMARY_PREFIX + "summary text"},
        {"role": "assistant", "content": "recent", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "after compaction", "agent_name": "COMPUTRON"},
    ]


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
    assert build_llm_view(events) == [
        {"role": "user", "content": _INTENT_PREFIX + "user wants Z now"},
        {"role": "assistant", "content": _SUMMARY_PREFIX + "summary"},
        {"role": "assistant", "content": "recent", "agent_name": "COMPUTRON"},
    ]


def test_only_latest_compaction_applied():
    """Older compactions stay in the log for audit but don't reshape the LLM
    view — only the most recent one matters."""
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
    assert build_llm_view(events) == [
        {"role": "user", "content": "anchor"},
        {"role": "assistant", "content": _SUMMARY_PREFIX + "NEW SUMMARY"},
        {"role": "assistant", "content": "y", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "after", "agent_name": "COMPUTRON"},
    ]


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
    assert build_llm_view(events) == [
        {"role": "user", "content": "delegate"},
        {"role": "assistant", "content": "spawn", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "root continues", "agent_name": "COMPUTRON"},
    ]


def test_compaction_kept_from_id_missing_returns_pin_and_summary():
    """If a compaction's kept_from_id isn't present (corrupt/raced log), the
    LLM view degrades to first user message + summary marker rather than
    raising or dropping the summary."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "anchor", evt_id="evt_u1"),
        _iter(ROOT, 0, content="x", evt_id="evt_i1"),
        _compaction(ROOT, "summary",
                    kept_from_id="evt_does_not_exist", kept_to_id="evt_i1"),
    ]
    assert build_llm_view(events) == [
        {"role": "user", "content": "anchor"},
        {"role": "assistant", "content": _SUMMARY_PREFIX + "summary"},
    ]


def test_llm_view_augments_first_user_message_with_attachments():
    """The LLM view appends the attachment block so the model can find the
    uploaded files in the sandbox."""
    user_evt = _user(ROOT, "look at this")
    user_evt["attachments"] = [{
        "filename": "a.txt", "content_type": "text/plain",
        "path": "/home/computron/uploads/a.txt",
    }]
    events = [_started(ROOT, "COMPUTRON"), user_evt]
    assert build_llm_view(events) == [
        {"role": "user", "content":
            "look at this\n\n[Attached files written to virtual computer]\n"
            "  - a.txt (text/plain) -> /home/computron/uploads/a.txt"},
    ]
