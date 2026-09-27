"""E2E CRUD test for the http (token) integration.

The credential providers (iCloud, Gmail, Google Workspace) validate against
a real upstream at add time, so their "Add → connected" path can't run in
e2e without real secrets. The http broker is different: it readies without
probing the token, so the whole lifecycle — create, read, update, delete —
works end-to-end against a fake base URL and token, no real service needed.

This remains useful adapter-specific coverage alongside the comprehensive,
stateful fake-broker lifecycle suite.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.pages import SettingsPage

# The backend derives the id suffix from the label via the same sanitizer
# used for emails: lowercased, non-[a-z0-9_-] runs collapsed to "-".
_LABEL = "E2E HTTP API"
_ID = "http_e2e-http-api"
_RENAMED = "E2E HTTP API (renamed)"
_CANCEL_LABEL = "E2E Cancelled API"
_CANCEL_ID = "http_e2e-cancelled-api"


def test_http_integration_crud(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations

    # ── CREATE ───────────────────────────────────────────────────────
    flow = tab.open_add_flow_from_empty()
    flow.pick_provider("http").next_()
    flow.fill_http(
        base_url="https://api.example.com",
        token="fake-token-123",
        label=_LABEL,
    )
    expect(flow.submit).to_be_enabled()
    flow.submit.click()

    # Registration starts with no grants. Select the one generic HTTP tool,
    # then continue through review.
    expect(flow.tools_heading).to_be_visible()
    flow.page.get_by_test_id("integration-tool-http.request").click()
    flow.next_()
    expect(flow.done).to_be_visible()
    flow.done.click()
    expect(tab.row(_ID)).to_be_visible()

    # ── READ ─────────────────────────────────────────────────────────
    tab.open_detail(_ID)
    expect(page.get_by_role("heading", name=_LABEL, exact=True)).to_be_visible()
    tab.change_tools_button(_ID).click()
    expect(tab.tool_checkbox("http.request")).to_be_checked()
    tab.cancel_edit(_ID)

    # ── UPDATE ───────────────────────────────────────────────────────
    # Label is meta-only (no respawn). Edit and save, then reload the page
    # so the assertion reads the value back from the vault, not local state.
    tab.open_connection_settings()
    tab.rename_button(_ID).click()
    tab.label_input(_ID).fill(_RENAMED)
    tab.save_and_wait(_ID)

    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    tab.open_detail(_ID)
    expect(page.get_by_role("heading", name=_RENAMED, exact=True)).to_be_visible()
    tab.change_tools_button(_ID).click()
    # A label-only edit must preserve the exact grant set.
    expect(tab.tool_checkbox("http.request")).to_be_checked()

    # Exact grant updates persist independently from the connection label.
    tab.tool_checkbox("http.request").click()
    tab.save_button(_ID).click()
    expect(tab.row(_ID)).to_contain_text("No tools selected")
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    tab.open_detail(_ID)
    tab.change_tools_button(_ID).click()
    expect(tab.tool_checkbox("http.request")).not_to_be_checked()
    tab.cancel_edit(_ID)

    # Credential replacement keeps the same connection identity and does not
    # route through Add (which would collide with the deterministic ID).
    tab.open_connection_settings()
    tab.reconnect_button(_ID).click()
    expect(page.get_by_test_id("integration-reconnect-flow")).to_be_visible()
    page.get_by_test_id("wizard-base-url").fill("https://api-v2.example.com")
    page.get_by_test_id("wizard-token").fill("replacement-token")
    page.get_by_test_id("wizard-submit").click()
    expect(page.get_by_test_id("integration-reconnect-flow")).to_be_hidden()
    expect(tab.row(_ID)).to_be_visible()

    # ── DELETE ───────────────────────────────────────────────────────
    # ConfirmButton arms on the first click and fires on the second.
    tab.remove_button(_ID).click()
    tab.remove_button(_ID).click()
    expect(tab.row(_ID)).to_be_hidden()
    expect(tab.empty_state_heading).to_be_visible()


def test_cancelling_after_connect_removes_the_setup_owned_integration(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    flow = tab.open_add_flow_from_empty()
    flow.pick_provider("http").next_()
    flow.fill_http(
        base_url="https://api.example.com",
        token="cancel-me",
        label=_CANCEL_LABEL,
    )
    flow.submit.click()

    # The connection now exists with zero grants so its tools can be shown.
    # Cancelling owns the cleanup and does not close the modal until DELETE
    # succeeds.
    expect(flow.tools_heading).to_be_visible()
    page.get_by_test_id("wizard-exit").click()
    expect(flow.root).to_be_hidden()

    # Reload from the supervisor-backed list so absence is not just stale UI.
    tab = SettingsPage(page).goto_integrations().integrations
    expect(tab.row(_CANCEL_ID)).to_be_hidden()
