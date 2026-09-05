"""A child compacts its real tool history and the activity view restores it."""

import time

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, spawn
from tests.e2e._runtime import agent_profile, compaction_script, compaction_settings, delete_conversation, resume, run_turn
from tests.e2e.pages import ChatView, NetworkView, RecentConversations


def _tokens(value):
    return f"{int(value / 1000 + 0.5)}k" if value >= 1000 else str(value)


def test_sub_agent_compaction_shows_in_activity_view(page: Page):
    conversation = f"e2e_activity_compaction_{time.time_ns()}"
    with compaction_settings(), agent_profile(context_window=1000, compaction_threshold=0.01) as profile:
        try:
            run_turn(conversation, spawn(compaction_script(), profile=profile["id"], name="CODE_REVIEWER") + say("root done"))
            events = resume(conversation)["events"]
            compacted = [e for e in events if e["type"] == "compaction"]
            assert len(compacted) == 1 and compacted[0]["depth"] == 1
            # A child compaction must not become a root conversation chip.
            event = compacted[0]
            ChatView(page).goto().new_conversation()
            RecentConversations(page).open_by_id(conversation)
            expect(page.get_by_test_id("compaction-chip")).to_have_count(0)
            network = NetworkView(page).open()
            activity = network.select_agent(1)
            assert activity.agent_id == event["agent_id"]
            row = activity.root.get_by_test_id("activity-row-compaction")
            expect(row).to_have_count(1)
            expect(row).to_contain_text("compacted")
            stats = event["stats"]
            assert stats["saved_tokens"] > 0
            expect(row).to_contain_text(f"saved {_tokens(stats['saved_tokens'])} ({int(stats['saved_ratio'] * 100 + 0.5)}%)")
            panel = activity.root.get_by_test_id("activity-compaction-panel")
            expect(panel).not_to_be_visible()
            activity.root.get_by_test_id("activity-compaction-summary").click()
            expect(panel).to_be_visible()
            expect(panel).to_contain_text(_tokens(stats["context_before"]))
            expect(panel).to_contain_text(_tokens(stats["context_after"]))
            expect(panel).to_contain_text(event["summary_text"])
            assert stats["scope"]["tool_results"] > 0
            expect(panel).to_contain_text(f"{stats['scope']['tool_results']} tool calls")
        finally:
            delete_conversation(conversation)
