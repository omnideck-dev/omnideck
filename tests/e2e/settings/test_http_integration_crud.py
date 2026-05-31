"""E2E CRUD test for the http (token) integration.

The credential providers (iCloud, Gmail, Google Workspace) validate against
a real upstream at add time, so their "Add → connected" path can't run in
e2e without real secrets. The http broker is different: it readies without
probing the token, so the whole lifecycle — create, read, update, delete —
works end-to-end against a fake base URL and token, no real service needed.

That's exactly why this flow earns an e2e test: nothing else exercises the
add → list → edit → remove path against a live supervisor and broker.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.pages import SettingsPage

# The backend derives the id suffix from the label via the same sanitizer
# used for emails: lowercased, non-[a-z0-9_-] runs collapsed to "-".
_LABEL = "E2E HTTP API"
_ID = "http_e2e-http-api"
_RENAMED = "E2E HTTP API (renamed)"


def test_http_integration_crud(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations

    # ── CREATE ───────────────────────────────────────────────────────
    modal = tab.open_add_modal_from_empty()
    modal.pick_provider("http").next_()
    modal.fill_http(
        base_url="https://api.example.com",
        token="fake-token-123",
        label=_LABEL,
    )
    expect(modal.submit).to_be_enabled()
    modal.submit.click()

    # Plain save (no upstream probe) → success screen, then back to the list.
    expect(modal.done).to_be_visible()
    modal.done.click()
    expect(tab.row(_ID)).to_be_visible()

    # ── READ ─────────────────────────────────────────────────────────
    tab.open_detail(_ID)
    expect(tab.label_input(_ID)).to_have_value(_LABEL)

    # ── UPDATE ───────────────────────────────────────────────────────
    # Label is meta-only (no respawn). Edit and save, then reload the page
    # so the assertion reads the value back from the vault, not local state.
    tab.label_input(_ID).fill(_RENAMED)
    tab.save_button(_ID).click()

    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    tab.open_detail(_ID)
    expect(tab.label_input(_ID)).to_have_value(_RENAMED)

    # ── DELETE ───────────────────────────────────────────────────────
    # ConfirmButton arms on the first click and fires on the second.
    tab.remove_button(_ID).click()
    tab.remove_button(_ID).click()
    expect(tab.row(_ID)).to_be_hidden()
    expect(tab.empty_state_heading).to_be_visible()
