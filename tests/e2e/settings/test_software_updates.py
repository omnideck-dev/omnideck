"""E2E coverage for the React software-update UI and desktop bridge."""

import json

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.pages import SettingsPage

DESKTOP_UPDATE_BRIDGE = """
(() => {
    const state = {
        calls: [],
        checkResult: null,
        current: null,
        listener: null,
    };
    const announce = (update) => {
        state.current = update;
        state.listener?.(update);
    };

    window.__updateBridgeE2E = {
        announce,
        calls: state.calls,
        setCheckResult(update) {
            state.checkResult = update;
        },
    };
    window.omnideckHost = Object.freeze({
        onUpdate(listener) {
            state.listener = listener;
            return () => {
                if (state.listener === listener) state.listener = null;
            };
        },
        currentUpdate() {
            state.calls.push('currentUpdate');
            return Promise.resolve(state.current);
        },
        checkForUpdate() {
            state.calls.push('checkForUpdate');
            announce(state.checkResult);
            return Promise.resolve(state.current);
        },
        installUpdate() {
            state.calls.push('installUpdate');
            return Promise.resolve();
        },
        deferUpdate() {
            state.calls.push('deferUpdate');
            if (state.current) announce({ ...state.current, deferred: true });
            return Promise.resolve();
        },
        skipUpdate() {
            state.calls.push('skipUpdate');
            announce(null);
            return Promise.resolve();
        },
    });
})();
"""


def _enable_update_notices(route: Route) -> None:
    """Keep update-notice preferences deterministic without changing server state."""
    if route.request.method != "GET":
        route.continue_()
        return
    response = route.fetch()
    settings = response.json()
    settings["software_updates_automatic"] = True
    settings["software_updates_notify"] = True
    route.fulfill(
        status=response.status,
        content_type="application/json",
        body=json.dumps(settings),
    )


@pytest.fixture
def desktop_update_page(page: Page) -> Page:
    """Load pages with a deterministic fake of the desktop update bridge."""
    page.add_init_script(script=DESKTOP_UPDATE_BRIDGE)
    page.route("**/api/settings", _enable_update_notices)
    return page


def test_browser_hides_desktop_update_controls_and_notice(page: Page) -> None:
    """A normal browser does not expose controls that require the desktop host."""
    SettingsPage(page).goto_system()

    expect(page.get_by_test_id("updates-settings-group")).to_have_count(0)
    expect(page.get_by_test_id("software-update-notice")).to_have_count(0)


def test_desktop_shows_controls_and_manual_check_can_install(
    desktop_update_page: Page,
) -> None:
    """Hosted UI exposes update settings and forwards manual update actions."""
    page = desktop_update_page
    SettingsPage(page).goto_system()

    updates = page.get_by_test_id("updates-settings-group")
    status = page.get_by_test_id("software-update-status")
    expect(updates).to_be_visible()
    expect(updates.get_by_text("Install updates automatically", exact=True)).to_be_visible()
    expect(updates.get_by_role("switch", name="Install updates automatically")).to_be_checked()
    expect(updates.get_by_text("Tell me when an update is ready", exact=True)).to_be_visible()
    expect(updates.get_by_role("switch", name="Tell me when an update is ready")).to_be_checked()
    expect(status).to_contain_text("Omnideck is up to date")

    page.evaluate(
        "update => window.__updateBridgeE2E.setCheckResult(update)",
        {"version": "9.9.9", "deferred": False},
    )
    status.get_by_role("button", name="Check now").click()

    expect(status).to_contain_text("Omnideck 9.9.9 is ready")
    status.get_by_role("button", name="Update now").click()
    calls = page.evaluate("() => window.__updateBridgeE2E.calls")
    assert "checkForUpdate" in calls
    assert "installUpdate" in calls


def test_update_event_shows_notice_and_later_hides_it(
    desktop_update_page: Page,
) -> None:
    """A bridge update event opens the notice until the user defers it."""
    page = desktop_update_page
    page.goto("/")
    page.get_by_test_id("sidebar-settings").wait_for(state="visible")
    notice = page.get_by_test_id("software-update-notice")
    expect(notice).to_have_count(0)

    page.evaluate(
        "update => window.__updateBridgeE2E.announce(update)",
        {"version": "9.9.9", "deferred": False},
    )

    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Omnideck 9.9.9 is ready")
    expect(notice.get_by_role("button", name="Update now")).to_be_visible()
    expect(notice.get_by_role("button", name="Later")).to_be_visible()
    expect(notice.get_by_role("button", name="Skip this version")).to_be_visible()

    notice.get_by_role("button", name="Later").click()

    expect(notice).to_have_count(0)
    calls = page.evaluate("() => window.__updateBridgeE2E.calls")
    assert "deferUpdate" in calls
