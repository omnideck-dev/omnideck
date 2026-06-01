"""E2E test for deeply nested agent trees (3 levels).

Verifies the network view correctly renders a root → sub-agent →
sub-sub-agent hierarchy with proper parent-child relationships.
"""

from playwright.sync_api import Page, Route, expect

from tests.e2e.network._sse import _evt, build_jsonl
from tests.e2e.pages import ChatView, NetworkView


DEEP_TREE_EVENTS = build_jsonl([
    # Level 0: root
    _evt({"type": "agent_started", "agent_id": "root",
          "agent_name": "computron", "parent_agent_id": None,
          "instruction": "Orchestrate a complex task"},
         agent_id="root", agent_name="computron"),
    _evt({"type": "user_message", "content": "do the thing",
          "attachments": [], "is_nudge": False},
         agent_id="root", agent_name="computron"),
    # Level 1: planner (child of root)
    _evt({"type": "agent_started", "agent_id": "planner",
          "agent_name": "planner_agent", "parent_agent_id": "root",
          "instruction": "Plan the approach"},
         agent_id="planner", agent_name="planner_agent", depth=1),
    # Level 2: executor (child of planner)
    _evt({"type": "agent_started", "agent_id": "executor",
          "agent_name": "executor_agent", "parent_agent_id": "planner",
          "instruction": "Execute step 1"},
         agent_id="executor", agent_name="executor_agent", depth=2),
    # Level 2: reviewer (child of planner)
    _evt({"type": "agent_started", "agent_id": "reviewer",
          "agent_name": "reviewer_agent", "parent_agent_id": "planner",
          "instruction": "Review the output"},
         agent_id="reviewer", agent_name="reviewer_agent", depth=2),
    # Leaf agents: executor (content + tool) and reviewer (content).
    _evt({"type": "content", "content": "Executed step 1."},
         agent_id="executor", agent_name="executor_agent", depth=2),
    _evt({"type": "tool_call", "name": "bash"},
         agent_id="executor", agent_name="executor_agent", depth=2),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Executed step 1.", "thinking": None,
          "tool_calls": [{"id": "tc1", "name": "bash", "arguments": None}]},
         agent_id="executor", agent_name="executor_agent", depth=2),
    _evt({"type": "content", "content": "Looks good."},
         agent_id="reviewer", agent_name="reviewer_agent", depth=2),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Looks good.", "thinking": None, "tool_calls": []},
         agent_id="reviewer", agent_name="reviewer_agent", depth=2),
    # Complete leaf agents.
    _evt({"type": "agent_completed", "agent_id": "executor",
          "agent_name": "executor_agent", "status": "success"},
         agent_id="executor", agent_name="executor_agent", depth=2),
    _evt({"type": "agent_completed", "agent_id": "reviewer",
          "agent_name": "reviewer_agent", "status": "success"},
         agent_id="reviewer", agent_name="reviewer_agent", depth=2),
    # Complete planner.
    _evt({"type": "content", "content": "Plan executed."},
         agent_id="planner", agent_name="planner_agent", depth=1),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "Plan executed.", "thinking": None,
          "tool_calls": []},
         agent_id="planner", agent_name="planner_agent", depth=1),
    _evt({"type": "agent_completed", "agent_id": "planner",
          "agent_name": "planner_agent", "status": "success"},
         agent_id="planner", agent_name="planner_agent", depth=1),
    # Complete root.
    _evt({"type": "content", "content": "All done."},
         agent_id="root", agent_name="computron"),
    _evt({"type": "iteration", "iteration_index": 0,
          "content": "All done.", "thinking": None, "tool_calls": []},
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
        body=DEEP_TREE_EVENTS,
    )


def test_three_level_tree_renders_all_cards(page: Page):
    """A 3-level deep tree shows all 4 agent cards."""
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat)

    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    expect(network.indicator).to_be_visible(timeout=5000)
    expect(network.indicator).to_contain_text("4 agents")

    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)
    assert network.agent_cards.count() == 4

    network.card_by_name("Computron")
    network.card_by_name("Planner Agent")
    network.card_by_name("Executor Agent")
    network.card_by_name("Reviewer Agent")


def test_mid_level_agent_shows_sub_agent_badge(page: Page):
    """Planner (level 1) shows '2 sub-agents' badge for its children."""
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat)

    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    planner = network.card_by_name("Planner Agent")
    expect(planner.sub_agent_badge).to_contain_text("2 sub-agents")

    root = network.card_by_name("Computron")
    expect(root.sub_agent_badge).to_contain_text("1 sub-agent")


def test_leaf_agents_have_no_sub_agent_badge(page: Page):
    """Executor and Reviewer (level 2) have no sub-agent badges."""
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat)

    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    executor = network.card_by_name("Executor Agent")
    reviewer = network.card_by_name("Reviewer Agent")
    expect(executor.sub_agent_badge).not_to_be_visible()
    expect(reviewer.sub_agent_badge).not_to_be_visible()


def test_drill_into_nested_agent_activity(page: Page):
    """Can navigate into a level-2 agent's activity view from the network."""
    chat = ChatView(page).goto().new_conversation()
    page.route("**/api/chat", _mock_chat)

    chat.send("test")
    chat.wait_streaming()

    network = NetworkView(page)
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    executor = network.card_by_name("Executor Agent")
    executor.click()
    page.wait_for_timeout(500)

    activity_view = page.get_by_test_id("agent-activity-view")
    expect(activity_view).to_be_visible(timeout=5000)
