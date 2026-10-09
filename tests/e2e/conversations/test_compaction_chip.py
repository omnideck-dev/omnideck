"""Compaction chip renders statistics produced by real context management."""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import say
from tests.e2e._runtime import agent_profile, compaction_settings, delete_conversation, run_turn
from tests.e2e.pages import ChatView, RecentConversations


@pytest.fixture
def compacted_conversation():
    conversation = f"e2e_compaction_chip_{time.time_ns()}"
    with compaction_settings(), agent_profile(context_window=1000, compaction_threshold=0.01) as profile:
        try:
            events = []
            # The summarizer also uses FakeProvider: this compacted user input
            # gives its real model call a concise reply via the same protocol.
            oranges = (
                "what about oranges? Compare their sweetness, acidity, seasonal varieties, and common cooking uses. "
                + say("Oranges are citrus fruit.")
            )
            for prompt in ("tell me about apples", oranges, "compare fruit varieties", "summarize the comparison"):
                events += run_turn(conversation, prompt, profile_id=profile["id"])
            compactions = [e["payload"] for e in events if e["payload"]["type"] == "compaction"]
            assert len(compactions) == 1
            assert compactions[0]["summary_text"]
            assert compactions[0]["user_intent_summary"]
            assert compactions[0]["stats"]["saved_tokens"] > 0
            yield conversation, compactions[0]
        finally:
            delete_conversation(conversation)


def _tokens(value):
    return f"{int(value / 1000 + 0.5)}k" if value >= 1000 else str(value)


def test_compaction_chip_renders_between_turns(page: Page, compacted_conversation):
    conversation, _event = compacted_conversation
    ChatView(page).goto().new_conversation()
    RecentConversations(page).open_by_id(conversation)
    chip = page.get_by_test_id("compaction-chip")
    expect(chip).to_have_count(1)
    expect(chip).to_contain_text("earlier conversation compacted")
    expect(page.get_by_test_id("turn")).to_have_count(4)


def test_compaction_chip_expands_and_shows_stats(page: Page, compacted_conversation):
    conversation, event = compacted_conversation
    ChatView(page).goto().new_conversation()
    RecentConversations(page).open_by_id(conversation)
    panel = page.get_by_test_id("compaction-panel")
    expect(panel).not_to_be_visible()
    page.get_by_test_id("compaction-chip").click()
    expect(panel).to_be_visible()
    stats = event["stats"]
    expect(panel).to_contain_text(_tokens(stats["context_before"]))
    expect(panel).to_contain_text(_tokens(stats["context_after"]))
    expect(panel).to_contain_text(f"saved {_tokens(stats['saved_tokens'])} ({int(stats['saved_ratio'] * 100 + 0.5)}%)")
    expect(panel).to_contain_text("0 tool calls")
    expect(panel).to_contain_text(f"{_tokens(stats['summary_tokens'])} tokens")
    expect(panel).to_contain_text("What the agent thinks you are working on")
    expect(panel).to_contain_text(event["user_intent_summary"])
    expect(panel).to_contain_text("What the agent thinks it has done")
    expect(panel).to_contain_text(event["summary_text"])
