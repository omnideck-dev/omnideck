"""Full Browser-profile workflows through the product UI."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._api import ApiClient
from tests.e2e._protocol import open_url
from tests.e2e.pages import AgentsPage, BrowserControl, ChatView
from tests.e2e.preview._browser_fixture import fixture_url, install_fixture


@pytest.fixture(scope="module", autouse=True)
def _fixture_page():
    install_fixture()


def _open_browser(page: Page) -> BrowserControl:
    page.goto("/")
    page.get_by_test_id("sidebar-nav-browser").click()
    page.get_by_test_id("browser-page").wait_for(state="visible")
    return BrowserControl(page).wait_loaded(timeout=30_000)


def _load_profile(page: Page, name: str) -> BrowserControl:
    profile_select = page.get_by_test_id("browser-profile-select")
    if profile_select.inner_text().strip() == name:
        return BrowserControl(page).wait_loaded(timeout=30_000)
    profile_select.click()
    page.get_by_role("option", name=name, exact=True).click()
    replace = page.get_by_test_id("replace-browser-modal")
    replace.wait_for(state="visible")
    replace.get_by_role("button", name="Use Empty" if name == "Empty" else "Load profile").click()
    replace.wait_for(state="hidden")
    return BrowserControl(page).wait_loaded(timeout=30_000)


def _assert_report(browser: BrowserControl, value: str) -> None:
    browser.goto(fixture_url("profile-report"))
    expect(browser.address).to_have_value(
        re.compile(rf"mode=profile-result&cookie={value}&local={value}&indexed={value}"), timeout=15_000
    )


def _save_new_profile(
    page: Page,
    api_client: ApiClient,
    *,
    name: str,
    value: str,
) -> dict:
    browser = (
        BrowserControl(page).wait_loaded(timeout=30_000)
        if page.get_by_test_id("browser-page").is_visible()
        else _open_browser(page)
    )
    browser = _load_profile(page, "Empty")
    browser.goto(fixture_url("profile-seed") + f"&value={value}")
    expect(browser.address).to_have_value(
        re.compile(rf"mode=profile-seeded&value={value}"),
        timeout=15_000,
    )
    page.get_by_test_id("browser-save-state").click()
    modal = page.get_by_test_id("save-browser-modal")
    modal.get_by_test_id("browser-save-target").click()
    page.get_by_role("option", name="Create new profile", exact=True).click()
    modal.get_by_label("Profile name").fill(name)
    modal.get_by_test_id("browser-save-confirm").click()
    modal.wait_for(state="hidden")
    return next(profile for profile in api_client.get("/api/browser/profiles").json() if profile["name"] == name)


def _create_browser_agent(
    api_client: ApiClient,
    *,
    agent_id: str,
    name: str,
    profile_id: str,
) -> None:
    base_agent = next(profile for profile in api_client.get("/api/profiles").json() if profile["id"] == "omnideck")
    response = api_client.post(
        "/api/profiles",
        data={
            "id": agent_id,
            "name": name,
            "provider": base_agent["provider"],
            "model": base_agent["model"],
            "skills": [],
            "browser_access": True,
            "browser_profile_id": profile_id,
        },
    )
    assert response.status == 201


def _select_agent(page: Page, name: str) -> None:
    page.get_by_label("Agent profile").click()
    page.get_by_role("option", name=name, exact=True).click()


def _assert_agent_browser_state(chat: ChatView, value: str) -> None:
    chat.send(open_url(fixture_url("profile-report"))).wait_streaming(timeout=30_000)
    chat.preview.browser_tab.wait_for(state="visible", timeout=10_000)
    chat.preview.select_tab(chat.preview.browser_tab)
    browser = BrowserControl(
        chat.page,
        root_testid="desktop-view-browser",
    ).wait_loaded(timeout=30_000)
    if not browser.address.is_visible():
        browser.take_control(timeout=15_000)
    expect(browser.address).to_have_value(
        re.compile(rf"mode=profile-result&cookie={value}&local={value}&indexed={value}"), timeout=15_000
    )


def test_explicit_save_load_and_start_fresh(page: Page):
    """Only an explicit save changes Default; fresh and reload are isolated."""
    browser = _open_browser(page)

    browser.goto(fixture_url("profile-seed") + "&value=alpha")
    expect(browser.address).to_have_value(re.compile("mode=profile-seeded&value=alpha"), timeout=15_000)

    page.get_by_test_id("browser-save-state").click()
    modal = page.get_by_test_id("save-browser-modal")
    modal.wait_for(state="visible")
    expect(modal.get_by_test_id("browser-save-target")).to_have_attribute("data-value", "default")
    expect(modal).to_contain_text("access any sites you are logged into")
    expect(modal).to_contain_text("localhost")
    modal.get_by_test_id("browser-save-confirm").click()
    modal.wait_for(state="hidden")

    browser = _load_profile(page, "Empty")
    _assert_report(browser, "")

    browser = _load_profile(page, "Default")
    _assert_report(browser, "alpha")

    # The working Browser changes to beta, but starting Empty and loading
    # Default again restores the explicitly saved alpha snapshot because
    # browsing never writes back. Selecting the already-loaded option is a no-op.
    browser.goto(fixture_url("profile-seed") + "&value=beta")
    expect(browser.address).to_have_value(re.compile("mode=profile-seeded&value=beta"), timeout=15_000)
    browser = _load_profile(page, "Empty")
    browser = _load_profile(page, "Default")
    _assert_report(browser, "alpha")


def test_agent_browser_access_and_profile_are_saved(page: Page, api_client: ApiClient):
    """Agent configuration exposes Browser access and a profile, not a skill."""
    profile_id = "browser_profile_e2e"
    base_agent = next(profile for profile in api_client.get("/api/profiles").json() if profile["id"] == "omnideck")
    response = api_client.post(
        "/api/profiles",
        data={
            "id": profile_id,
            "name": "Browser Profile E2E",
            "provider": base_agent["provider"],
            "model": base_agent["model"],
            "skills": [],
            "browser_access": False,
            "browser_profile_id": None,
        },
    )
    assert response.status == 201
    try:
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)
        browser_access = page.get_by_role("switch", name="Allow Browser access")
        expect(browser_access).not_to_be_checked()
        browser_access.locator("xpath=ancestor::label[1]").click()
        profile_select = page.get_by_test_id("agent-browser-profile-select")
        expect(profile_select).to_have_attribute("data-value", "default")
        profile_select.click()
        menu = page.get_by_test_id("agent-browser-profile-select-menu")
        expect(menu).to_be_visible()
        assert profile_select.bounding_box()["width"] >= 240
        assert menu.bounding_box()["width"] >= 240
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("profile-skill-browser")).to_have_count(0)
        agents.builder.save()

        saved = api_client.get(f"/api/profiles/{profile_id}")
        assert saved.status == 200
        assert saved.json()["browser_access"] is True
        assert saved.json()["browser_profile_id"] == "default"
        assert "browser" not in saved.json()["skills"]
    finally:
        api_client.delete(f"/api/profiles/{profile_id}")


def test_create_profile_and_rename_it_in_settings(page: Page, api_client: ApiClient):
    """Save-as-new requires a name/icon and Settings manages its identity."""
    _open_browser(page)
    page.get_by_test_id("browser-save-state").click()
    modal = page.get_by_test_id("save-browser-modal")
    modal.get_by_test_id("browser-save-target").click()
    page.get_by_role("option", name="Create new profile", exact=True).click()
    modal.get_by_label("Profile name").fill("Work accounts E2E")
    modal.get_by_test_id("browser-icon-picker-trigger").click()
    page.get_by_test_id("browser-icon-bi-briefcase").click()
    modal.get_by_test_id("browser-save-confirm").click()
    modal.wait_for(state="hidden")

    created = next(
        profile for profile in api_client.get("/api/browser/profiles").json() if profile["name"] == "Work accounts E2E"
    )
    try:
        assert created["icon"] == "bi-briefcase"
        page.get_by_role("button", name="Manage browser profiles").click()
        page.get_by_test_id("browser-profiles-settings").wait_for(state="visible")
        row = page.get_by_test_id(f"browser-profile-{created['id']}")
        row.click()
        editor = page.get_by_test_id("browser-profile-editor")
        editor.get_by_label("Name").fill("Client accounts E2E")
        editor.get_by_role("button", name="Save").click()
        expect(row).to_contain_text("Client accounts E2E")
        assert api_client.get("/api/browser/profiles").status == 200

        page.get_by_role("button", name="Open in Browser").click()
        page.get_by_test_id("browser-page").wait_for(state="visible")
        replace = page.get_by_test_id("replace-browser-modal")
        expect(replace).to_be_hidden()

        page.reload()
        page.get_by_test_id("browser-page").wait_for(state="visible")
        expect(page.get_by_test_id("replace-browser-modal")).to_be_hidden()
    finally:
        api_client.delete(f"/api/browser/profiles/{created['id']}")


def test_takeover_from_empty_can_save_and_assign_new_profile(page: Page, api_client: ApiClient):
    """A takeover of Empty saves as new and asks before assigning it."""
    agent_id = "empty_browser_e2e"
    base_agent = next(profile for profile in api_client.get("/api/profiles").json() if profile["id"] == "omnideck")
    response = api_client.post(
        "/api/profiles",
        data={
            "id": agent_id,
            "name": "Empty Browser E2E",
            "provider": base_agent["provider"],
            "model": base_agent["model"],
            "skills": [],
            "browser_access": True,
            "browser_profile_id": None,
        },
    )
    assert response.status == 201
    created_profile_id = None
    try:
        chat = ChatView(page).goto().new_conversation()
        selector = page.get_by_label("Agent profile")
        selector.click()
        page.get_by_role("option", name="Empty Browser E2E", exact=True).click()
        chat.send(open_url(fixture_url("profile-seed") + "&value=takeover")).wait_streaming(timeout=30_000)
        chat.preview.browser_tab.wait_for(state="visible", timeout=10_000)
        chat.preview.select_tab(chat.preview.browser_tab)
        browser = BrowserControl(page).wait_loaded(timeout=30_000).take_control()
        expect(browser.address).to_have_value(re.compile("mode=profile-seeded&value=takeover"), timeout=15_000)

        page.get_by_test_id("browser-takeover-save-state").click()
        modal = page.get_by_test_id("save-browser-modal")
        expect(modal.get_by_test_id("browser-save-target")).to_have_attribute("data-value", "__new__")
        modal.get_by_label("Profile name").fill("Takeover E2E")
        expect(modal.get_by_label("Use this profile for Empty Browser E2E next time")).not_to_be_checked()
        modal.get_by_label("Use this profile for Empty Browser E2E next time").check()
        modal.get_by_test_id("browser-save-confirm").click()
        modal.wait_for(state="hidden")

        saved_agent = api_client.get(f"/api/profiles/{agent_id}").json()
        assert saved_agent["browser_profile_id"] is not None
        created_profile_id = saved_agent["browser_profile_id"]
        saved_profile = next(
            profile for profile in api_client.get("/api/browser/profiles").json() if profile["id"] == created_profile_id
        )
        assert saved_profile["name"] == "Takeover E2E"
    finally:
        api_client.delete(f"/api/profiles/{agent_id}")
        if created_profile_id:
            api_client.delete(f"/api/browser/profiles/{created_profile_id}")


def test_profile_settings_remove_one_site_or_clear_all_state(
    page: Page,
    api_client: ApiClient,
):
    """Storage cleanup preserves profile identity and requires confirmation."""
    removable = _save_new_profile(
        page,
        api_client,
        name="Remove site E2E",
        value="remove-site",
    )
    clearable = _save_new_profile(
        page,
        api_client,
        name="Clear state E2E",
        value="clear-state",
    )
    try:
        page.get_by_role("button", name="Manage browser profiles").click()
        page.get_by_test_id("browser-profiles-settings").wait_for(state="visible")

        removable_row = page.get_by_test_id(f"browser-profile-{removable['id']}")
        removable_row.click()
        remove_site = page.get_by_test_id("browser-profile-remove-site-localhost")
        remove_site.click()
        confirm_remove = page.get_by_test_id("browser-profile-remove-site-dialog")
        expect(confirm_remove).to_be_visible()
        confirm_remove.get_by_role("button", name="Remove site").click()
        expect(confirm_remove).to_be_hidden()
        expect(removable_row).to_contain_text("0 sites")
        assert (
            next(
                profile
                for profile in api_client.get("/api/browser/profiles").json()
                if profile["id"] == removable["id"]
            )["sites"]
            == []
        )

        clearable_row = page.get_by_test_id(f"browser-profile-{clearable['id']}")
        clearable_row.click()
        clear_state = page.get_by_test_id("browser-profile-clear-state")
        clear_state.click()
        expect(clear_state).to_have_accessible_name("Clear all state?")
        clear_state.click()
        expect(clearable_row).to_contain_text("0 sites")
        expect(page.get_by_test_id("browser-profile-clear-state")).to_be_disabled()
        assert (
            next(
                profile
                for profile in api_client.get("/api/browser/profiles").json()
                if profile["id"] == clearable["id"]
            )["sites"]
            == []
        )
    finally:
        for profile in (removable, clearable):
            api_client.delete(f"/api/browser/profiles/{profile['id']}")


def test_switching_agents_replaces_browser_with_each_assigned_profile(
    page: Page,
    api_client: ApiClient,
):
    """One conversation never carries site state across agent assignments."""
    alpha = _save_new_profile(
        page,
        api_client,
        name="Alpha isolation E2E",
        value="alpha-isolated",
    )
    beta = _save_new_profile(
        page,
        api_client,
        name="Beta isolation E2E",
        value="beta-isolated",
    )
    agent_ids = ("alpha_browser_agent_e2e", "beta_browser_agent_e2e")
    _create_browser_agent(
        api_client,
        agent_id=agent_ids[0],
        name="Alpha Browser Agent E2E",
        profile_id=alpha["id"],
    )
    _create_browser_agent(
        api_client,
        agent_id=agent_ids[1],
        name="Beta Browser Agent E2E",
        profile_id=beta["id"],
    )

    try:
        chat = ChatView(page).goto().new_conversation()
        _select_agent(page, "Alpha Browser Agent E2E")
        _assert_agent_browser_state(chat, "alpha-isolated")

        _select_agent(page, "Beta Browser Agent E2E")
        _assert_agent_browser_state(chat, "beta-isolated")

        _select_agent(page, "Alpha Browser Agent E2E")
        _assert_agent_browser_state(chat, "alpha-isolated")
    finally:
        for agent_id in agent_ids:
            api_client.delete(f"/api/profiles/{agent_id}")
        for profile in (alpha, beta):
            api_client.delete(f"/api/browser/profiles/{profile['id']}")
