"""E2E: a conversation that spans multiple root agent profiles and
contains a compaction event.

The migrator (and the resume API) must surface the same compaction chip
regardless of profile switches between turns. Specifically, the chip's
scope.user_messages should reflect ALL root user messages compacted,
not just the ones for the agent_name on the compaction event.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e.pages import ChatView, RecentConversations

CONV_DIR = "/var/lib/computron/conversations"


def _seed_multi_profile_conv(conv_id: str, *, title: str | None = None) -> None:
    """Seed: three root turns under two different profiles, a compaction,
    then one post-compaction turn under a third profile. The compaction
    summarized turns from MULTIPLE agent_names — its embedded stats
    must record the cross-profile scope correctly."""
    base = datetime.now(UTC)
    def _t(o: int) -> str:
        return (base + timedelta(seconds=o)).isoformat()

    def _turn(idx: int, agent_id: str, agent_name: str,
              user_text: str, assistant_text: str,
              t_offset: int) -> list[dict]:
        return [
            {"id": f"evt_{conv_id}_start_{idx}", "type": "agent_started",
             "timestamp": _t(t_offset), "conversation_id": conv_id,
             "agent_id": agent_id, "agent_name": agent_name,
             "parent_agent_id": None},
            {"id": f"evt_{conv_id}_user_{idx}", "type": "user_message",
             "timestamp": _t(t_offset + 1), "conversation_id": conv_id,
             "agent_id": agent_id, "agent_name": agent_name, "depth": 0,
             "content": user_text, "attachments": []},
            {"id": f"evt_{conv_id}_iter_{idx}", "type": "iteration",
             "timestamp": _t(t_offset + 2), "conversation_id": conv_id,
             "agent_id": agent_id, "agent_name": agent_name,
             "iteration_index": 0,
             "content": assistant_text, "thinking": None, "tool_calls": []},
            {"id": f"evt_{conv_id}_done_{idx}", "type": "agent_completed",
             "timestamp": _t(t_offset + 3), "conversation_id": conv_id,
             "agent_id": agent_id, "agent_name": agent_name,
             "status": "success"},
        ]

    events: list[dict] = []
    events += _turn(1, "root.profile_a.1", "PROFILE_A", "ask 1", "reply 1", 0)
    events += _turn(2, "root.profile_a.2", "PROFILE_A", "ask 2", "reply 2", 4)
    events += _turn(3, "root.profile_b.1", "PROFILE_B", "ask 3", "reply 3", 8)
    events.append({
        "id": f"evt_{conv_id}_compaction",
        "type": "compaction",
        "timestamp": _t(12),
        "conversation_id": conv_id,
        "agent_id": "root.profile_a.1",  # migrator tags with first root id
        "agent_name": "PROFILE_A",
        "kept_from_id": f"evt_{conv_id}_user_4",
        "kept_to_id": f"evt_{conv_id}_iter_4",
        "summary_text": "Earlier: user explored two profiles then switched.",
        "user_intent_summary": "exploring multi-profile behavior",
        # Migrator-shaped stats — cross-profile scope.
        "stats": {
            "scope": {"user_messages": 3, "iterations": 3, "tool_results": 0},
            "summary_chars": 53, "summary_tokens": 13, "summary_lines": 1,
            "model": "test-model", "input_char_count": 600, "elapsed_seconds": 1.0,
        },
    })
    events += _turn(4, "root.profile_c.1", "PROFILE_C", "post-compact ask", "post reply", 13)

    events_jsonl = "\n".join(json.dumps(e) for e in events) + "\n"
    meta = json.dumps({"title": title if title is not None else conv_id})
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
def test_compaction_chip_renders_across_profile_switches(page: Page):
    """The chip's scope.user_messages must reflect the cross-profile
    count (3) the migrator embedded, not the count for the single
    agent_name tagged on the compaction event (1)."""
    nonce = time.time_ns()
    conv_id = f"e2e_multi_profile_compact_{nonce}"
    _seed_multi_profile_conv(conv_id)
    try:
        ChatView(page).goto()
        RecentConversations(page).open_by_title(conv_id)
        chip = page.get_by_test_id("compaction-chip").first
        expect(chip).to_be_visible(timeout=5_000)
        expect(chip).to_contain_text("earlier conversation compacted")
        chip.click()
        panel = page.get_by_test_id("compaction-panel").first
        expect(panel).to_be_visible()
        expect(panel).to_contain_text(
            "Earlier: user explored two profiles then switched.",
        )
        expect(panel).to_contain_text("exploring multi-profile behavior")
    finally:
        _cleanup(conv_id)
