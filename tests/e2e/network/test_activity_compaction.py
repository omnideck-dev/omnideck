"""E2E: a sub-agent's compaction shows up in its activity view.

A compaction inside a sub-agent (depth>0) never appears in the main chat
(which filters depth>0). It should instead surface as a marker on the
sub-agent's activity rail. This seeds a root -> sub-agent tree where the
sub-agent carries a depth-1 compaction, then drills into that agent's
activity view and asserts the marker renders and expands.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, NetworkView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"
ROOT = "root.computron.1"
SUB = "root.computron.1.code_reviewer.2"


def _seed(conv_id: str) -> None:
    base = datetime.now(UTC)

    def _t(o: int) -> str:
        return (base + timedelta(seconds=o)).isoformat()

    events = [
        {"id": "s_root", "type": "agent_started", "timestamp": _t(0),
         "conversation_id": conv_id, "agent_id": ROOT, "agent_name": "COMPUTRON",
         "parent_agent_id": None, "depth": 0},
        {"id": "u1", "type": "user_message", "timestamp": _t(1),
         "conversation_id": conv_id, "agent_id": ROOT, "agent_name": "COMPUTRON",
         "depth": 0, "content": "review the code", "attachments": []},
        {"id": "sr1", "type": "spawn_requested", "timestamp": _t(2),
         "conversation_id": conv_id, "agent_id": ROOT, "agent_name": "COMPUTRON",
         "depth": 0, "correlation_id": "corr-1"},
        # Sub-agent: starts, does a turn, compacts, finishes.
        {"id": "s_sub", "type": "agent_started", "timestamp": _t(3),
         "conversation_id": conv_id, "agent_id": SUB, "agent_name": "CODE_REVIEWER",
         "parent_agent_id": ROOT, "depth": 1, "correlation_id": "corr-1",
         "instruction": "review the diff"},
        {"id": "i_sub", "type": "iteration", "timestamp": _t(4),
         "conversation_id": conv_id, "agent_id": SUB, "agent_name": "CODE_REVIEWER",
         "depth": 1, "iteration_index": 0,
         "content": "looking at the changes", "thinking": None, "tool_calls": []},
        {"id": "c_sub", "type": "compaction", "timestamp": _t(5),
         "conversation_id": conv_id, "agent_id": SUB, "agent_name": "CODE_REVIEWER",
         "depth": 1, "kept_from_id": "i_sub", "kept_to_id": "i_sub",
         "summary_text": "Reviewed the early portion of the diff.",
         "user_intent_summary": "user wants a thorough code review",
         "audit": {"model": "test-model", "input_char_count": 4000,
                   "elapsed_seconds": 2.5},
         "stats": {"context_before": 20000, "context_after": 8000,
                   "context_limit": 30000, "saved_tokens": 12000,
                   "saved_ratio": 0.6, "spanned_seconds": 4.0,
                   "scope": {"user_messages": 1, "iterations": 1,
                             "tool_results": 1},
                   "sub_agents_spawned": 0, "summary_chars": 40,
                   "summary_tokens": 10, "summary_lines": 1}},
        {"id": "d_sub", "type": "agent_completed", "timestamp": _t(6),
         "conversation_id": conv_id, "agent_id": SUB, "agent_name": "CODE_REVIEWER",
         "depth": 1, "status": "success"},
        {"id": "i_root", "type": "iteration", "timestamp": _t(7),
         "conversation_id": conv_id, "agent_id": ROOT, "agent_name": "COMPUTRON",
         "depth": 0, "iteration_index": 0,
         "content": "review done", "thinking": None, "tool_calls": []},
        {"id": "d_root", "type": "agent_completed", "timestamp": _t(8),
         "conversation_id": conv_id, "agent_id": ROOT, "agent_name": "COMPUTRON",
         "depth": 0, "status": "success"},
    ]
    events_jsonl = "\n".join(json.dumps(e) for e in events) + "\n"
    meta = json.dumps({"title": conv_id})
    container_exec(
        "import pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
        f"(d / 'metadata.json').write_text({meta!r})\n"
    )


def _cleanup(conv_id: str) -> None:
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
    )


@pytest.mark.e2e
def test_sub_agent_compaction_shows_in_activity_view(page: Page):
    conv_id = f"e2e_activity_compaction_{time.time_ns()}"
    _seed(conv_id)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)

        network = NetworkView(page)
        expect(network.indicator).to_be_visible(timeout=5_000)
        network.open()
        # Index 1 is the sole sub-agent (index 0 is the root).
        activity = network.select_agent(1)
        expect(activity.root).to_be_visible(timeout=5_000)

        # The compaction marker is on the rail, collapsed.
        row = page.get_by_test_id("activity-row-compaction")
        expect(row).to_be_visible()
        expect(row).to_contain_text("compacted")
        expect(row).to_contain_text("saved 12.0k (60%)")

        # Expanding reveals the stats + summary blocks.
        panel = page.get_by_test_id("activity-compaction-panel")
        expect(panel).not_to_be_visible()
        page.get_by_test_id("activity-compaction-summary").click()
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("20.0k")
        expect(panel).to_contain_text("8.0k")
        expect(panel).to_contain_text("Reviewed the early portion of the diff.")
        expect(panel).to_contain_text("user wants a thorough code review")
    finally:
        _cleanup(conv_id)
