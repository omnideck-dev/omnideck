"""E2E test for agent network indicator and card basics.

Driven by the fake LLM (MOCK_LLM): the root really spawns two
sub-agents, so the network indicator, card metadata (names, sub-agent
and tool badges, elapsed time), and navigation all reflect genuine
agent-lifecycle events.

  - research_agent: no tool work → no tool badge.
  - code_expert:    runs two bash commands → "2 tools" badge.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say, spawn
from tests.e2e.pages import ChatView, NetworkView

LLM_TIMEOUT = 180_000


@pytest.fixture
def network_after_turn(page: Page):
    """Spawn a real two-sub-agent tree and return the NetworkView."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(
        spawn(say("done"), profile="research_agent", name="research_agent")
        + spawn(bash("echo a") + bash("echo b") + say("done"),
                profile="code_expert", name="code_expert")
    ).wait_streaming(timeout=LLM_TIMEOUT)
    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=5000)
    return network


# ── Indicator ────────────────────────────────────────────────────────────


def test_indicator_shows_agent_count(page: Page, network_after_turn):
    """Indicator badge shows total agent count."""
    expect(network_after_turn.indicator).to_contain_text("3 agents")


def test_indicator_complete_status(page: Page, network_after_turn):
    """Indicator dot shows 'complete' when all agents finish."""
    dot = network_after_turn.indicator.locator("[class*='complete']")
    expect(dot).to_be_visible()


def test_indicator_clears_on_new_conversation(page: Page, network_after_turn):
    """Starting a new conversation removes the indicator."""
    ChatView(page).new_conversation()
    expect(network_after_turn.indicator).not_to_be_visible()


# ── Cards ────────────────────────────────────────────────────────────────


def test_cards_render_with_correct_names(page: Page, network_after_turn):
    """Network view shows cards with correct agent names."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)
    assert network_after_turn.agent_cards.count() == 3

    network_after_turn.card_by_name("Omnideck")
    network_after_turn.card_by_name("Research Agent")
    network_after_turn.card_by_name("Code Expert")


def test_root_card_sub_agent_badge(page: Page, network_after_turn):
    """Root card shows '2 sub-agents' badge."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    root = network_after_turn.card_by_name("Omnideck")
    expect(root.sub_agent_badge).to_contain_text("2 sub-agents")


def test_sub_agent_tool_badge(page: Page, network_after_turn):
    """Code Expert card shows '2 tools' badge."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    code_expert = network_after_turn.card_by_name("Code Expert")
    expect(code_expert.tool_badge).to_contain_text("2 tools")


def test_agent_without_tools_no_badge(page: Page, network_after_turn):
    """Research Agent has no tool badge."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    research = network_after_turn.card_by_name("Research Agent")
    expect(research.tool_badge).not_to_be_visible()


def test_leaf_agents_no_sub_agent_badge(page: Page, network_after_turn):
    """Leaf agents don't show sub-agent badges."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    research = network_after_turn.card_by_name("Research Agent")
    code_expert = network_after_turn.card_by_name("Code Expert")
    expect(research.sub_agent_badge).not_to_be_visible()
    expect(code_expert.sub_agent_badge).not_to_be_visible()


def test_cards_show_elapsed_time(page: Page, network_after_turn):
    """All cards display an elapsed time badge."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    for i in range(network_after_turn.agent_cards.count()):
        card = network_after_turn.card(i)
        expect(card.time_badge).to_be_visible()


# ── Navigation ───────────────────────────────────────────────────────────


def test_click_card_opens_activity_view(page: Page, network_after_turn):
    """Clicking a sub-agent card navigates to its activity view."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    activity = network_after_turn.select_agent(1)
    expect(activity.root).to_be_visible(timeout=5000)
