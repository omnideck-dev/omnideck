"""E2E tests for the compaction chip in a resumed conversation.

Seeds an events.jsonl with a compaction event embedded between two user
turns, opens the conversation, and verifies the chip renders and expands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"
AGENT_ID = "root.computron.1"
AGENT_NAME = "COMPUTRON"


def _build_events_jsonl(conv_id: str) -> str:
    """Synthesize an events.jsonl with a compaction event whose ``stats``
    are pre-computed so the chip renders without any post-hoc derivation.

    Wall-clock timestamps so the seeded conversation sorts above any
    live-created ones from earlier in the session and the
    ``RecentConversations.open_top()`` click lands here.

    Layout: two root turns separated by a compaction. Two ``agent_started``
    events anchor the per-turn message list so the chip's insertion
    point falls between them.
    """
    base = datetime.now(UTC)
    AGENT_ID_2 = "root.computron.2"

    def _t(offset: int) -> str:
        return (base + timedelta(seconds=offset)).isoformat()

    events = [
        {"id": "evt_started_1", "type": "agent_started",
         "timestamp": _t(0), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": AGENT_NAME,
         "parent_agent_id": None},
        {"id": "evt_u1", "type": "user_message",
         "timestamp": _t(1), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": AGENT_NAME, "depth": 0,
         "content": "tell me about apples", "attachments": []},
        {"id": "evt_i1", "type": "iteration",
         "timestamp": _t(2), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": AGENT_NAME,
         "iteration_index": 0,
         "content": "apples are a pome fruit.",
         "thinking": None, "tool_calls": []},
        {"id": "evt_completed_1", "type": "agent_completed",
         "timestamp": _t(3), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": AGENT_NAME,
         "status": "success"},
        {"id": "evt_c1", "type": "compaction",
         "timestamp": _t(4), "conversation_id": conv_id,
         "agent_id": AGENT_ID, "agent_name": AGENT_NAME,
         "kept_from_id": "evt_i2", "kept_to_id": "evt_i2",
         "summary_text": "User asked about apples. Agent explained pome fruit.",
         "user_intent_summary": "user is researching fruit varieties",
         "audit": {"model": "test-model", "input_char_count": 4000,
                   "elapsed_seconds": 2.5},
         "stats": {
             "context_before": 20000,
             "context_after": 8000,
             "context_limit": 30000,
             "saved_tokens": 12000,
             "saved_ratio": 0.6,
             "spanned_seconds": 4.0,
             "scope": {"user_messages": 1, "iterations": 1,
                       "tool_results": 0},
             "sub_agents_spawned": 0,
             "summary_chars": 52,
             "summary_tokens": 13,
             "summary_lines": 1,
         }},
        {"id": "evt_started_2", "type": "agent_started",
         "timestamp": _t(5), "conversation_id": conv_id,
         "agent_id": AGENT_ID_2, "agent_name": AGENT_NAME,
         "parent_agent_id": None},
        {"id": "evt_u2", "type": "user_message",
         "timestamp": _t(6), "conversation_id": conv_id,
         "agent_id": AGENT_ID_2, "agent_name": AGENT_NAME, "depth": 0,
         "content": "what about oranges?", "attachments": []},
        {"id": "evt_i2", "type": "iteration",
         "timestamp": _t(7), "conversation_id": conv_id,
         "agent_id": AGENT_ID_2, "agent_name": AGENT_NAME,
         "iteration_index": 0,
         "content": "oranges are a citrus fruit.",
         "thinking": None, "tool_calls": []},
        {"id": "evt_completed_2", "type": "agent_completed",
         "timestamp": _t(8), "conversation_id": conv_id,
         "agent_id": AGENT_ID_2, "agent_name": AGENT_NAME,
         "status": "success"},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _seed(conv_id: str, *, title: str | None = None) -> None:
    events_jsonl = _build_events_jsonl(conv_id)
    # Default title = conv_id so the recent-list search can find it by
    # nonce — robust to recency ordering and exercises search too.
    meta = json.dumps({"title": title if title is not None else conv_id})
    script = (
        "import pathlib\n"
        f"d = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "d.mkdir(parents=True, exist_ok=True)\n"
        f"(d / 'events.jsonl').write_text({events_jsonl!r})\n"
        f"(d / 'metadata.json').write_text({meta!r})\n"
        f"print('{conv_id}')\n"
    )
    container_exec(script)


def _cleanup(conv_id: str) -> None:
    container_exec(
        "import shutil, pathlib\n"
        f"p = pathlib.Path('{CONV_DIR}/{conv_id}')\n"
        "if p.exists(): shutil.rmtree(p)\n"
    )


def test_compaction_chip_renders_between_turns(page: Page):
    """Open a seeded conversation and verify the chip appears with
    the expected turn-count label."""
    conv_id = "e2e-compaction-chip-render"
    _seed(conv_id)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        chip = page.get_by_test_id("compaction-chip").first
        expect(chip).to_be_visible()
        expect(chip).to_contain_text("earlier conversation compacted")
        # No N-turn suffix on the chip — compactions can fire mid-turn
        # so a turn count would overclaim. Panel still shows scope.
    finally:
        _cleanup(conv_id)


def test_compaction_chip_expands_and_shows_stats(page: Page):
    """Clicking the chip reveals the stats panel with savings, scope,
    and both summary sections."""
    conv_id = "e2e-compaction-chip-expand"
    _seed(conv_id)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        chip = page.get_by_test_id("compaction-chip").first
        panel = page.get_by_test_id("compaction-panel").first
        expect(panel).not_to_be_visible()
        chip.click()
        expect(panel).to_be_visible()
        expect(panel).to_contain_text("20.0k")
        expect(panel).to_contain_text("8.0k")
        expect(panel).to_contain_text("saved 12.0k (60%)")
        expect(panel).to_contain_text("0 tool calls")
        expect(panel).to_contain_text("13 tokens")
        expect(panel).to_contain_text(
            "What the agent thinks you are working on",
        )
        expect(panel).to_contain_text("user is researching fruit varieties")
        expect(panel).to_contain_text("What the agent thinks it has done")
        expect(panel).to_contain_text(
            "User asked about apples. Agent explained pome fruit.",
        )
    finally:
        _cleanup(conv_id)
