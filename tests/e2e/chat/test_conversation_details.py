"""Details discovers real agent resources and reopens their existing views."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, open_url, spawn
from tests.e2e.pages import AgentActivityView, BrowserControl, ChatView, DesktopLayout, NetworkView
from tests.e2e.preview._browser_fixture import fixture_url, install_fixture


@pytest.fixture(scope="module", autouse=True)
def _browser_fixture():
    install_fixture()


@pytest.mark.parametrize("resource", ["browser", "terminal"])
def test_details_reopens_workspace_resource_with_existing_content(page: Page, resource: str):
    chat = ChatView(page).goto().new_conversation()
    first_url = fixture_url("idle") + "&details=first"
    second_url = fixture_url("idle") + "&details=second"
    directive = (
        open_url(first_url) + open_url(second_url)
        if resource == "browser"
        else bash("printf 'details-first-output\\n'") + bash("printf 'details-second-output\\n'")
    )
    chat.send(directive).wait_streaming(timeout=30_000)
    desktop = DesktopLayout(page)
    tab = desktop.tab(resource)
    view = page.locator(f"[data-view-type='workspace-resource'][data-view-resource-id='{resource}']")
    expect(tab).to_be_visible()
    tab.click()
    expect(view).to_be_visible()
    view_id = view.get_attribute("data-view-id")

    def assert_content():
        if resource == "browser":
            browser = BrowserControl(page).wait_loaded()
            expect(browser.tabs).to_have_count(2)
            expect(browser.tab(1)).to_have_attribute("aria-selected", "true")
            expect(view.get_by_text(first_url, exact=True)).to_be_visible()
            expect(browser.page_title).to_have_text("bfix")
            browser.tab(2).click()
            expect(view.get_by_text(second_url, exact=True)).to_be_visible()
            browser.tab(1).click()
            expect(view.get_by_text(first_url, exact=True)).to_be_visible()
        else:
            expect(view).to_contain_text("details-first-output")
            expect(view).to_contain_text("details-second-output")

    if resource == "browser":
        # Verify both remote pages survive closing their enclosing workspace view.
        BrowserControl(page).wait_loaded().tab(1).click()
    assert_content()
    NetworkView(page).show_details()
    details = page.get_by_role("region", name="Conversation details")
    row = details.get_by_role("button", name=re.compile(rf"^{resource.title()}(?: |$)"))
    expect(row).to_be_visible()
    page.keyboard.press("Escape")

    desktop.choose_tab_action(resource, "close")
    expect(tab).to_have_count(0)
    expect(view).to_have_count(0)
    NetworkView(page).show_details()
    expect(row).to_be_visible()
    row.click()

    expect(details).not_to_be_visible()
    expect(tab).to_have_count(1)
    expect(tab).to_have_attribute("aria-selected", "true")
    expect(view).to_have_count(1)
    expect(view).to_have_attribute("data-view-id", view_id)
    assert_content()

    # Selecting the already-open row focuses the same view without duplicating it.
    NetworkView(page).show_details()
    expect(row).to_be_visible()
    row.click()
    expect(tab).to_have_count(1)
    expect(view).to_have_count(1)
    expect(view).to_have_attribute("data-view-id", view_id)
    assert_content()


def test_details_groups_spawned_resources_and_opens_their_owner(page: Page):
    chat = ChatView(page).goto().new_conversation()
    alpha_url = fixture_url("idle") + "&owner=alpha"
    chat.send(
        spawn(open_url(alpha_url) + bash("printf 'alpha-terminal-output'"),
              profile="research_agent", name="ALPHA")
        + spawn(bash("printf 'bravo-terminal-output'"), profile="research_agent", name="BRAVO")
    ).wait_streaming(timeout=40_000)

    # Resolve identities through the existing Network page object, independent
    # of the Details rows whose owner routing is being tested.
    network = NetworkView(page).open()
    alpha_id = network.select_agent_by_name("ALPHA").agent_id
    AgentActivityView(page).back_to_network()
    bravo_id = network.select_agent_by_name("BRAVO").agent_id
    AgentActivityView(page).back_to_network().back_to_chat()
    expect(page.locator("[data-view-type='workspace-resource']")).to_have_count(0)

    NetworkView(page).show_details()
    details = page.get_by_role("region", name="Conversation details")
    browsers = details.get_by_role("region", name="Browsers", exact=True)
    terminals = details.get_by_role("region", name="Terminals", exact=True)
    expect(browsers.get_by_role("button")).to_have_count(1)
    expect(terminals.get_by_role("button")).to_have_count(2)
    expect(browsers.get_by_role("button", name=re.compile(r"^ALPHA Browser"))).to_be_visible()
    expect(terminals.get_by_role("button", name=re.compile(r"^ALPHA Terminal"))).to_be_visible()
    expect(terminals.get_by_role("button", name=re.compile(r"^BRAVO Terminal"))).to_be_visible()

    for owner, agent_id, resource in [
        ("ALPHA", alpha_id, "browser"),
        ("BRAVO", bravo_id, "terminal"),
        ("ALPHA", alpha_id, "terminal"),
    ]:
        NetworkView(page).show_details()
        details.get_by_role("button", name=re.compile(rf"^{owner} {resource.title()}")).click()
        activity = AgentActivityView(page, agent_id)
        expect(activity.execution_tab(resource)).to_have_attribute("aria-selected", "true")
        view = activity.execution_view(resource)
        expect(view).to_have_count(1)
        expect(view).to_be_visible()
        if resource == "browser":
            expect(view.get_by_test_id("browser-frame")).to_be_visible()
            expect(view.get_by_text(alpha_url, exact=True)).to_be_visible()
        else:
            expect(view).to_contain_text(f"{owner.lower()}-terminal-output")
            other_owner = "bravo" if owner == "ALPHA" else "alpha"
            expect(view).not_to_contain_text(f"{other_owner}-terminal-output")
