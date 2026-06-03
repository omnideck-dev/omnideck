"""E2E test for deeply nested agent trees (3 levels).

Driven by the fake LLM (MOCK_LLM): the root really spawns a planner,
which in turn spawns two leaf agents — a genuine
root -> sub-agent -> sub-sub-agent hierarchy, so the network view's
parent/child badges and navigation reflect real lifecycle events.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, spawn
from tests.e2e.pages import ChatView, NetworkView


@pytest.fixture
def deep_tree(page: Page):
    """Spawn a real 3-level tree: root -> planner -> (executor, reviewer)."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(
        spawn(
            spawn(say("done"), name="executor_agent")
            + spawn(say("done"), name="reviewer_agent")
            + say("planned"),
            name="planner_agent",
        )
    ).wait_streaming()
    return NetworkView(page)


def test_three_level_tree_renders_all_cards(page: Page, deep_tree):
    """A 3-level deep tree shows all 4 agent cards."""
    network = deep_tree
    expect(network.indicator).to_be_visible(timeout=5000)
    expect(network.indicator).to_contain_text("4 agents")

    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)
    assert network.agent_cards.count() == 4

    network.card_by_name("Omnideck")
    network.card_by_name("Planner Agent")
    network.card_by_name("Executor Agent")
    network.card_by_name("Reviewer Agent")


def test_mid_level_agent_shows_sub_agent_badge(page: Page, deep_tree):
    """Planner (level 1) shows '2 sub-agents' badge for its children."""
    network = deep_tree
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    planner = network.card_by_name("Planner Agent")
    expect(planner.sub_agent_badge).to_contain_text("2 sub-agents")

    root = network.card_by_name("Omnideck")
    expect(root.sub_agent_badge).to_contain_text("1 sub-agent")


def test_leaf_agents_have_no_sub_agent_badge(page: Page, deep_tree):
    """Executor and Reviewer (level 2) have no sub-agent badges."""
    network = deep_tree
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    executor = network.card_by_name("Executor Agent")
    reviewer = network.card_by_name("Reviewer Agent")
    expect(executor.sub_agent_badge).not_to_be_visible()
    expect(reviewer.sub_agent_badge).not_to_be_visible()


def test_drill_into_nested_agent_activity(page: Page, deep_tree):
    """Can navigate into a level-2 agent's activity view from the network."""
    network = deep_tree
    network.open()
    expect(network.agent_cards.first).to_be_visible(timeout=5000)

    executor = network.card_by_name("Executor Agent")
    executor.click()
    page.wait_for_timeout(500)

    activity_view = page.get_by_test_id("agent-activity-view")
    expect(activity_view).to_be_visible(timeout=5000)
