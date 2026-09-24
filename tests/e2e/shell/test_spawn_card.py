"""E2E test for the spawn_agent grouped card in the chat stream.

Driven by the fake LLM (MOCK_LLM): the root agent really spawns two
sub-agents in parallel via spawn_agent, and we verify the SpawnCard
groups them into one inline card and that clicking a row drills into
that agent's activity view — the same code path the app uses.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, spawn
from tests.e2e.pages import ChatView


@pytest.fixture
def chat_after_spawn(page: Page) -> ChatView:
    """Send a turn that spawns two named sub-agents in parallel."""
    chat = ChatView(page).goto().new_conversation()
    # Two consecutive spawns → the fake emits both spawn_agent calls in
    # one response → the UI groups them into a single spawn card. The
    # display name is title-cased per word for the row label, so a
    # lowercase "research_agent" renders as "Research Agent".
    chat.send(
        spawn(say("done"), profile="research_agent", name="research_agent")
        + spawn(say("done"), profile="code_expert", name="code_expert")
    ).wait_streaming()
    expect(page.get_by_test_id("spawn-card")).to_be_visible(timeout=5000)
    return chat


def test_spawn_card_renders_in_chat(page: Page, chat_after_spawn):
    """The spawn card appears inline in the assistant turn."""
    card = page.get_by_test_id("spawn-card")
    expect(card).to_contain_text("spawn_agent")
    expect(card).to_contain_text("2 agents")


def test_spawn_card_has_a_row_per_agent(page: Page, chat_after_spawn):
    """One clickable row per spawned sub-agent."""
    rows = page.get_by_test_id("spawn-card-row")
    expect(rows).to_have_count(2)
    card = page.get_by_test_id("spawn-card")
    expect(card).to_contain_text("Research Agent")
    expect(card).to_contain_text("Code Expert")


def test_raw_spawn_tool_call_is_hidden(page: Page, chat_after_spawn):
    """The raw spawn_agent tool-call line is replaced by the card."""
    tool_calls = page.get_by_test_id("entry-tool-call")
    for i in range(tool_calls.count()):
        assert "spawn_agent" not in (tool_calls.nth(i).text_content() or "")


def test_click_row_opens_agent_activity_view(page: Page, chat_after_spawn):
    """Clicking a spawn-card row drills into that agent's activity view."""
    page.get_by_test_id("spawn-card-row").first.click()
    page.wait_for_timeout(500)
    expect(page.get_by_test_id("agent-activity-view")).to_be_visible(timeout=5000)
