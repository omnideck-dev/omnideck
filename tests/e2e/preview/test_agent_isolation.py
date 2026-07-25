"""E2E coverage for agent-bound Browser, Terminal, and artifact output.

Sub-agent workspace resources are discoverable from Agent Activity but do not open
tabs by themselves. Once the user opens one, its view stays bound to the
producing agent while the user moves between Chat, Network, and other agents.
Artifacts remain manual, durable tabs.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, open_url, send_file, spawn, write_file
from tests.e2e.pages import AgentActivityView, BrowserControl, ChatView, NetworkView


@pytest.fixture(scope="module")
def isolation_page(browser, browser_context_args):
    """Spawn two named sub-agents with distinct output."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    chat = ChatView(page).goto().new_conversation()

    one = "/home/computron/one.txt"
    two = "/home/computron/two.txt"
    agent_one = (
        bash('echo "agent-one"')
        + open_url("https://example.com")
        + write_file(one, "hello from agent one")
        + send_file(one)
    )
    agent_two = (
        bash('echo "agent-two"')
        + write_file(two, "hello from agent two")
        + send_file(two)
    )
    chat.send(
        spawn(agent_one, profile="code_expert", name="ALPHA")
        + spawn(agent_two, profile="code_expert", name="BRAVO")
    ).wait_streaming(timeout=40_000)

    network = NetworkView(page)
    assert network.indicator.is_visible(), (
        "Network indicator not visible — sub-agents may not have been spawned"
    )

    yield page

    page.close()
    context.close()


def _open_agent(page: Page, name: str) -> AgentActivityView:
    activity_root = page.get_by_test_id("agent-activity-view")
    if activity_root.is_visible():
        network = AgentActivityView(page).back_to_network()
    elif page.get_by_test_id("agent-network").is_visible():
        network = NetworkView(page)
    else:
        network = NetworkView(page).open()
    return network.select_agent_by_name(name)


def test_subagents_spawned_without_auto_opening_views(isolation_page: Page):
    """Output is advertised on the agent, but no sub-agent tab steals focus."""
    network = NetworkView(isolation_page).open()
    assert network.agent_cards.count() >= 3

    activity = network.select_agent_by_name("ALPHA")
    expect(activity.browser_action).to_be_visible()
    expect(activity.terminal_action).to_be_visible()
    expect(activity.execution_tab("browser")).to_have_count(0)
    expect(activity.execution_tab("terminal")).to_have_count(0)


def test_agent_terminal_opens_explicitly_and_keeps_agent_identity(
    isolation_page: Page,
):
    """The Terminal action opens only the selected agent's accumulated output."""
    activity = _open_agent(isolation_page, "ALPHA").open_terminal()

    expect(activity.execution_tab("terminal")).to_be_visible()
    view = activity.execution_view("terminal")
    expect(view).to_be_visible()
    expect(view).to_contain_text("agent-one")
    expect(view).not_to_contain_text("agent-two")


def test_agent_browser_opens_explicitly(isolation_page: Page):
    """The Browser action opens the selected sub-agent's captured browser."""
    activity = _open_agent(isolation_page, "ALPHA").open_browser()

    expect(activity.execution_tab("browser")).to_be_visible(timeout=10_000)
    expect(activity.execution_view("browser")).to_be_visible()
    BrowserControl(isolation_page).wait_loaded(timeout=15_000)


def test_agent_artifact_opens_manually_and_is_durable(isolation_page: Page):
    """An activity file output opens only on Preview and becomes an artifact tab."""
    activity = _open_agent(isolation_page, "ALPHA")
    expect(isolation_page.get_by_test_id("view-tab-artifact:one.txt")).to_have_count(0)

    activity.open_first_file_preview()
    tab = isolation_page.get_by_test_id("view-tab-artifact:one.txt")
    expect(tab).to_be_visible()
    expect(
        isolation_page.locator(
            "[data-view-type='artifact-file'][data-active='true']"
        )
    ).to_contain_text("hello from agent one")

    activity = _open_agent(isolation_page, "BRAVO")
    expect(tab).to_be_visible()
    activity.open_first_file_preview()
    expect(
        isolation_page.locator(
            "[data-view-type='artifact-file'][data-active='true']"
        )
    ).to_contain_text("hello from agent two")


def test_open_agent_views_remain_bound_while_returning_to_chat(
    isolation_page: Page,
):
    """Navigation does not reinterpret already-open tabs as root-agent output."""
    activity = _open_agent(isolation_page, "BRAVO").open_terminal()
    bravo_id = activity.agent_id
    alpha = _open_agent(isolation_page, "ALPHA")
    alpha_id = alpha.agent_id
    alpha.back_to_network().back_to_chat()

    expect(
        isolation_page.locator(
            "[data-view-type='workspace-resource']"
            f"[data-view-owner-id='{alpha_id}']"
        )
    ).to_have_count(2)
    expect(
        isolation_page.locator(
            "[data-view-type='workspace-resource']"
            f"[data-view-owner-id='{bravo_id}']"
        )
    ).to_have_count(1)
    expect(isolation_page.get_by_test_id("chat-title-bar")).to_be_visible()
