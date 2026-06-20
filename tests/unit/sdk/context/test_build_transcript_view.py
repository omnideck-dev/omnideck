"""Tests for build_transcript_view — the user-facing events.jsonl → messages view.

The transcript is the conversation as it happened: no compaction collapse and
the user's text verbatim (no attachment augmentation). These tests pin those
two distinctions from the LLM view, plus parity on the user/assistant/tool walk.
"""

from __future__ import annotations

import pytest

from sdk.context._view import _SUMMARY_PREFIX, build_transcript_view
from tests.unit.sdk.context._event_builders import (
    ROOT,
    _compaction,
    _iter,
    _started,
    _tool,
    _user,
)

pytestmark = [pytest.mark.unit]


def test_transcript_view_does_not_augment_attachments():
    """The augmented `[Attached files written to virtual computer]` block is
    for the LLM; the transcript shows what the user actually typed."""
    user_evt = _user(ROOT, "look at this")
    user_evt["attachments"] = [{
        "filename": "a.txt", "content_type": "text/plain",
        "path": "/home/computron/uploads/a.txt",
    }]
    events = [_started(ROOT, "COMPUTRON"), user_evt]
    assert build_transcript_view(events) == [
        {"role": "user", "content": "look at this"},
    ]


def test_transcript_view_ignores_compaction():
    """The defining contract: the transcript view never collapses at a
    compaction. It returns the full conversation — no summary marker, no
    kept-range clipping — where the LLM view would have collapsed."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "first user msg", evt_id="evt_u1"),
        _iter(ROOT, 0, content="working", evt_id="evt_i1"),
        _iter(ROOT, 1, content="still working", evt_id="evt_i2"),
        _iter(ROOT, 2, content="recent", evt_id="evt_i3"),
        _compaction(ROOT, "summary text",
                    kept_from_id="evt_i3", kept_to_id="evt_i3"),
        _iter(ROOT, 3, content="after compaction", evt_id="evt_i4"),
    ]
    assert build_transcript_view(events) == [
        {"role": "user", "content": "first user msg"},
        {"role": "assistant", "content": "working", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "still working", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "recent", "agent_name": "COMPUTRON"},
        {"role": "assistant", "content": "after compaction", "agent_name": "COMPUTRON"},
    ]


def test_transcript_view_walks_nudges_tools_and_thinking():
    """Parity: the transcript walks user/assistant/tool the same way the LLM
    view does — it only skips the compaction collapse and the attachment
    augmentation."""
    events = [
        _started(ROOT, "COMPUTRON"),
        _user(ROOT, "start", evt_id="evt_u1"),
        _iter(ROOT, 0, content="ok", thinking="planning",
              tool_calls=[{"id": "c1", "name": "shell", "arguments": {"cmd": "ls"}}],
              evt_id="evt_i1"),
        _tool(ROOT, "shell", "a.txt", call_id="c1"),
        _user(ROOT, "also do X", evt_id="evt_u2"),  # nudge
        _iter(ROOT, 1, content="done", evt_id="evt_i2"),
    ]
    assert build_transcript_view(events) == [
        {"role": "user", "content": "start"},
        {
            "role": "assistant",
            "thinking": "planning",
            "content": "ok",
            "tool_calls": [
                {"id": "c1", "function": {"name": "shell", "arguments": {"cmd": "ls"}}},
            ],
            "agent_name": "COMPUTRON",
        },
        {"role": "tool", "tool_call_id": "c1", "tool_name": "shell", "content": "a.txt"},
        {"role": "user", "content": "also do X"},
        {"role": "assistant", "content": "done", "agent_name": "COMPUTRON"},
    ]
