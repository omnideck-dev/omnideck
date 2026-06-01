"""E2E test for agent network indicator and card basics.

Mocks the /api/chat JSONL stream to control agent spawning precisely,
then verifies core network indicator behavior, card metadata, and
navigation.
"""

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.network._sse import _evt, build_jsonl
from tests.e2e.pages import ChatView, NetworkView


MOCK_EVENTS = build_jsonl([
    _evt({"type": "agent_started", "agent_id": "root",
          "agent_name": "computron", "parent_agent_id": None,
          "instruction": "Do some research and write code"},
         agent_id="root", agent_name="computron"),
    _evt({"type": "user_message", "content": "do the work",
          "attachments": [], "is_nudge": False},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_started", "agent_id": "sub1",
          "agent_name": "research_agent", "parent_agent_id": "root",
          "instruction": "Research the topic"},
         agent_id="sub1", agent_name="research_agent", depth=1),
    _evt({"type": "agent_started", "agent_id": "sub2",
          "agent_name": "code_expert", "parent_agent_id": "root",
          "instruction": "Write the implementation"},
         agent_id="sub2", agent_name="code_expert", depth=1),
    # Sub-agent 1: content stream + final iteration.
    _evt({"type": "content", "content": "Research complete."},
         agent_id="sub1", agent_name="research_agent", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Research complete.", "thinking": None,
          "tool_calls": []},
         agent_id="sub1", agent_name="research_agent", depth=1),
    # Sub-agent 2: two tool calls + final content.
    _evt({"type": "tool_call", "name": "bash"},
         agent_id="sub2", agent_name="code_expert", depth=1),
    _evt({"type": "tool_call", "name": "write_file"},
         agent_id="sub2", agent_name="code_expert", depth=1),
    _evt({"type": "content", "content": "Code written."},
         agent_id="sub2", agent_name="code_expert", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Code written.", "thinking": None,
          "tool_calls": [
              {"id": "tc1", "name": "bash", "arguments": None},
              {"id": "tc2", "name": "write_file", "arguments": None},
          ]},
         agent_id="sub2", agent_name="code_expert", depth=1),
    _evt({"type": "agent_completed", "agent_id": "sub1",
          "agent_name": "research_agent", "status": "success"},
         agent_id="sub1", agent_name="research_agent", depth=1),
    _evt({"type": "agent_completed", "agent_id": "sub2",
          "agent_name": "code_expert", "status": "success"},
         agent_id="sub2", agent_name="code_expert", depth=1),
    # Root's wrap-up iteration.
    _evt({"type": "content", "content": "Both tasks done."},
         agent_id="root", agent_name="computron"),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Both tasks done.", "thinking": None,
          "tool_calls": []},
         agent_id="root", agent_name="computron"),
    _evt({"type": "agent_completed", "agent_id": "root",
          "agent_name": "computron", "status": "success"},
         agent_id="root", agent_name="computron"),
    _evt({"type": "turn_end"},
         agent_id="root", agent_name="computron"),
])


def _mock_chat(route: Route):
    route.fulfill(
        status=200,
        headers={"Content-Type": "application/json"},
        body=MOCK_EVENTS,
    )


@pytest.fixture
def network_after_turn(page: Page):
    """Send a mocked multi-agent turn and return the NetworkView."""
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat)
    chat.send("test")
    chat.wait_streaming()
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
    page.unroute("**/api/chat")
    ChatView(page).new_conversation()
    expect(network_after_turn.indicator).not_to_be_visible()


# ── Cards ────────────────────────────────────────────────────────────────


def test_cards_render_with_correct_names(page: Page, network_after_turn):
    """Network view shows cards with correct agent names."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)
    assert network_after_turn.agent_cards.count() == 3

    network_after_turn.card_by_name("Computron")
    network_after_turn.card_by_name("Research Agent")
    network_after_turn.card_by_name("Code Expert")


def test_root_card_sub_agent_badge(page: Page, network_after_turn):
    """Root card shows '2 sub-agents' badge."""
    network_after_turn.open()
    expect(network_after_turn.agent_cards.first).to_be_visible(timeout=5000)

    root = network_after_turn.card_by_name("Computron")
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
