"""E2E CRUD test for the generic CLI-exec integration.

Same rationale as ``test_http_integration_crud.py``: the exec_broker binds
its socket and prints READY without probing any upstream, so — unlike the
credential providers that validate against a real service at add time —
the whole lifecycle (create, read, delete) runs end-to-end against a fake
command and secret, no real external service needed. There's no
secret-rotation step: swapping a CLI integration's credential is remove +
re-add, same as every other integration.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.pages import SettingsPage

_LABEL = "E2E CLI"
_ID = "cli_e2e-cli"


def test_cli_integration_crud(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations

    # ── CREATE ───────────────────────────────────────────────────────
    modal = tab.open_add_modal_from_empty()
    modal.pick_provider("cli").next_()
    modal.fill_cli(
        command="/bin/echo",
        var_name="FIXTURE_TOKEN",
        var_value="fake-value-123",
        label=_LABEL,
    )
    expect(modal.submit).to_be_enabled()
    modal.submit.click()

    expect(modal.done).to_be_visible()
    modal.done.click()
    expect(tab.row(_ID)).to_be_visible()

    # ── READ ─────────────────────────────────────────────────────────
    tab.open_detail(_ID)
    expect(tab.label_input(_ID)).to_have_value(_LABEL)

    # ── DELETE ───────────────────────────────────────────────────────
    tab.remove_button(_ID).click()
    tab.remove_button(_ID).click()
    expect(tab.row(_ID)).to_be_hidden()
    expect(tab.empty_state_heading).to_be_visible()
