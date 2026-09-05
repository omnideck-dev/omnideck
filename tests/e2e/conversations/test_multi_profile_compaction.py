"""Real compaction must account for earlier root turns across profile changes."""

import time

from playwright.sync_api import Page, expect

from tests.e2e._runtime import agent_profile, compaction_settings, delete_conversation, resume, run_turn
from tests.e2e.pages import ChatView, RecentConversations


def test_compaction_chip_renders_across_profile_switches(page: Page):
    conversation = f"e2e_multi_profile_compact_{time.time_ns()}"
    with compaction_settings(), agent_profile(name="Profile A") as a, agent_profile(name="Profile B") as b, agent_profile(
        name="Profile C", context_window=1000, compaction_threshold=0.01,
    ) as c:
        try:
            for i, profile in enumerate((a, b, a, b, c)):
                run_turn(conversation, f"exploring profiles, phase {i}", profile_id=profile["id"])
            events = resume(conversation)["events"]
            compactions = [e for e in events if e["type"] == "compaction"]
            assert len(compactions) == 1
            event = compactions[0]
            boundary = next(i for i, e in enumerate(events) if e["id"] == event["kept_from_id"])
            earlier = events[:boundary]
            assert {e["agent_name"] for e in earlier if e["type"] == "iteration"} == {"PROFILE A", "PROFILE B"}
            user_count = sum(e["type"] == "user_message" for e in earlier)
            assert user_count >= 2
            assert event["stats"]["scope"]["user_messages"] == user_count
            ChatView(page).goto().new_conversation()
            RecentConversations(page).open_by_id(conversation)
            chip = page.get_by_test_id("compaction-chip")
            expect(chip).to_have_count(1)
            expect(chip).to_contain_text("earlier conversation compacted")
            chip.click()
            panel = page.get_by_test_id("compaction-panel")
            expect(panel).to_be_visible()
            expect(panel).to_contain_text(event["summary_text"])
            expect(panel).to_contain_text(event["user_intent_summary"])
            scope = event["stats"]["scope"]
            expect(panel).to_contain_text(f"{scope['user_messages'] + scope['iterations']} messages")
        finally:
            delete_conversation(conversation)
