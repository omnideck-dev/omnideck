"""Full integration lifecycle coverage using the deterministic local broker."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec, container_run_root
from tests.e2e.pages import SettingsPage

_TOKEN = "omnideck-test-token"
_ID = "test_e2e-test-integration"
_LABEL = "E2E Test Integration"
_RENAMED = "E2E Test Integration (renamed)"
_CANCEL_ID = "test_cancelled-test-integration"
_BASE_URL = os.environ.get("OMNIDECK_URL", "http://localhost:9090")


@pytest.fixture(autouse=True)
def clean_fake_connections(page: Page) -> Iterator[None]:
    """Keep lifecycle scenarios independent if any one aborts early."""
    ids = (_ID, _CANCEL_ID)
    for integration_id in ids:
        page.request.delete(f"{_BASE_URL}/api/integrations/{integration_id}")
    yield
    for integration_id in ids:
        page.request.delete(f"{_BASE_URL}/api/integrations/{integration_id}")


def _invoke(
    integration_id: str,
    operation_id: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke through IntegrationService from the app UID inside the container."""
    arguments_json = json.dumps(arguments or {})
    script = f"""
import asyncio
import json
from integrations.broker_client import IntegrationError
from integrations.service import AGENT_CONTEXT, integration_service

async def main():
    try:
        result = await integration_service.invoke(
            AGENT_CONTEXT,
            {integration_id!r},
            {operation_id!r},
            json.loads({arguments_json!r}),
        )
    except IntegrationError as exc:
        print(json.dumps({{"ok": False, "error": type(exc).__name__, "message": str(exc)}}))
    else:
        print(json.dumps({{"ok": True, "result": result}}))

asyncio.run(main())
"""
    return json.loads(container_exec(script))


def _assert_vault_entry_absent(integration_id: str) -> None:
    creds = "/var/lib/omnideck/vault/creds"
    container_run_root(
        f"test ! -e {creds}/{integration_id}.meta && test ! -e {creds}/{integration_id}.enc",
    )


def test_fake_integration_full_lifecycle(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    flow = tab.open_add_flow()

    expect(page.get_by_test_id("provider-test")).to_be_visible()
    flow.pick_provider("test").next_()
    expect(page.get_by_text("Connect Test Integration")).to_be_visible()

    # The fake broker performs a real pre-READY credential check. A rejected
    # credential must roll the pending vault entry back and keep setup open.
    flow.fill_test(
        token="wrong-token",
        label=_LABEL,
    )
    flow.submit.click()
    expect(page.get_by_text("test broker rejected the credentials")).to_be_visible()
    _assert_vault_entry_absent(_ID)

    flow.token_input.fill(_TOKEN)
    flow.submit.click()
    expect(flow.tools_heading).to_be_visible()

    # Connection registration starts with no grants, and the broker enforces
    # that state before any tool is selected in the UI.
    denied = _invoke(_ID, "test.value.get")
    assert denied["ok"] is False
    assert denied["error"] == "IntegrationPermissionDenied"

    # Select only one of the two operations, finish Review, and prove that the
    # exact allowlist reaches the broker—not merely the UI.
    page.get_by_test_id("integration-tool-test.value.get").click()
    flow.next_()
    expect(page.get_by_text("1 tool selected")).to_be_visible()
    flow.done.click()
    expect(tab.row(_ID)).to_be_visible()

    assert _invoke(_ID, "test.value.get") == {
        "ok": True,
        "result": {"value": "initial value"},
    }
    denied = _invoke(_ID, "test.value.set", {"value": "changed"})
    assert denied["ok"] is False
    assert denied["error"] == "IntegrationPermissionDenied"

    # Editing the tool selection respawns the broker with the expanded exact
    # grant set. The stateful pair then proves successful write/read dispatch.
    tab.open_detail(_ID)
    expect(tab.tools_tab).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tab", name="Overview", exact=True)).to_have_count(0)
    # A contained collection must not regress to a dark toolbar band.
    picker = page.get_by_test_id("integration-operation-picker")
    assert picker.evaluate("""element => {
        const [toolbar, rows] = element.children;
        return getComputedStyle(toolbar).backgroundColor === getComputedStyle(rows).backgroundColor;
    }""")
    expect(tab.tool_checkbox("test.value.get")).to_be_checked()
    expect(tab.tool_checkbox("test.value.set")).not_to_be_checked()
    tab.tool_checkbox("test.value.set").click()
    tab.save_and_wait(_ID)
    expect(tab.tool_checkbox("test.value.set")).to_be_checked()

    assert _invoke(_ID, "test.value.set", {"value": "changed"}) == {
        "ok": True,
        "result": {"value": "changed"},
    }
    assert _invoke(_ID, "test.value.get") == {
        "ok": True,
        "result": {"value": "changed"},
    }

    # Label-only edits do not respawn the broker, so its in-memory state must
    # survive while metadata is persisted to the real vault.
    tab.connection_tab.click()
    tab.label_input(_ID).fill(_RENAMED)
    tab.save_and_wait(_ID)
    expect(tab.label_input(_ID)).to_have_value(_RENAMED)

    # Reload from the server so this assertion proves persisted metadata,
    # rather than merely observing the local input draft.
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    tab.open_detail(_ID)
    tab.connection_tab.click()
    expect(tab.label_input(_ID)).to_have_value(_RENAMED)
    assert _invoke(_ID, "test.value.get") == {
        "ok": True,
        "result": {"value": "changed"},
    }

    # Revoke a previously successful operation through the real UI. The next
    # invocation must fail at the broker even though the connection remains.
    tab.tools_tab.click()
    tab.tool_checkbox("test.value.set").click()
    tab.save_and_wait(_ID)
    denied = _invoke(_ID, "test.value.set", {"value": "must not be written"})
    assert denied["ok"] is False
    assert denied["error"] == "IntegrationPermissionDenied"
    assert _invoke(_ID, "test.value.get")["ok"] is True

    tab.remove_button(_ID).click()
    tab.remove_button(_ID).click()
    expect(tab.row(_ID)).to_be_hidden()
    removed = _invoke(_ID, "test.value.get")
    assert removed["ok"] is False
    assert removed["error"] == "IntegrationNotConnected"
    _assert_vault_entry_absent(_ID)


def test_cancelling_fake_setup_removes_connection_and_credential(page: Page) -> None:
    settings = SettingsPage(page).goto_integrations()
    tab = settings.integrations
    flow = tab.open_add_flow()
    flow.pick_provider("test").next_()
    flow.fill_test(
        token=_TOKEN,
        label="Cancelled test integration",
    )
    flow.submit.click()
    expect(flow.tools_heading).to_be_visible()

    page.get_by_test_id("wizard-exit").click()
    expect(flow.root).to_be_hidden()
    removed = _invoke(_CANCEL_ID, "test.value.get")
    assert removed["ok"] is False
    assert removed["error"] == "IntegrationNotConnected"
    _assert_vault_entry_absent(_CANCEL_ID)


@pytest.mark.parametrize("step", ["tools", "review"])
def test_failed_cancel_keeps_setup_open_and_can_retry(page: Page, step: str) -> None:
    flow = SettingsPage(page).goto_integrations().integrations.open_add_flow()
    flow.pick_provider("test").next_()
    flow.fill_test(token=_TOKEN, label="Cancelled test integration")
    flow.submit.click()
    expect(flow.tools_heading).to_be_visible()
    if step == "review":
        page.get_by_test_id("integration-tool-test.value.get").click()
        flow.next_()
        expect(flow.done).to_be_visible()
    cancel = (
        flow.root.get_by_role("button", name="Close", exact=True)
        if step == "review"
        else page.get_by_test_id("wizard-exit")
    )

    # Only the failing transport response is substituted. Registration and
    # the retry's deletion still use the actual supervisor and vault.
    url = f"**/api/integrations/{_CANCEL_ID}"

    def fail_delete(route):
        if route.request.method == "DELETE":
            route.fulfill(status=503, json={"error": {"code": "UNAVAILABLE", "message": "Temporary outage"}})
        else:
            route.continue_()

    page.route(url, fail_delete)
    cancel.click()
    expect(page.get_by_text("Couldn't cancel setup", exact=True)).to_be_visible()
    expect(flow.root).to_be_visible()
    assert _invoke(_CANCEL_ID, "test.value.get")["error"] == "IntegrationPermissionDenied"
    page.unroute(url, fail_delete)
    cancel.click()
    expect(flow.root).to_be_hidden()
    assert _invoke(_CANCEL_ID, "test.value.get")["error"] == "IntegrationNotConnected"
    _assert_vault_entry_absent(_CANCEL_ID)


def test_failed_reconnect_preserves_existing_grants_and_can_retry(page: Page) -> None:
    tab = SettingsPage(page).goto_integrations().integrations
    flow = tab.open_add_flow()
    flow.pick_provider("test").next_()
    flow.fill_test(token=_TOKEN, label=_LABEL)
    flow.submit.click()
    expect(flow.tools_heading).to_be_visible()
    tab.tool_checkbox("test.value.get").click()
    flow.next_()
    flow.done.click()
    expect(tab.row(_ID)).to_be_visible()
    tab.open_detail(_ID)
    tab.connection_tab.click()
    tab.reconnect_button(_ID).click()
    reconnect = page.get_by_test_id("integration-reconnect-flow")
    expect(reconnect).to_be_visible()
    page.get_by_test_id("wizard-token").fill("wrong-token")
    page.get_by_test_id("wizard-submit").click()
    expect(page.get_by_text("test broker rejected the credentials", exact=True)).to_be_visible()
    expect(reconnect).to_be_visible()
    assert _invoke(_ID, "test.value.get")["ok"] is True
    assert _invoke(_ID, "test.value.set", {"value": "denied"})["error"] == "IntegrationPermissionDenied"
    page.get_by_test_id("wizard-token").fill(_TOKEN)
    page.get_by_test_id("wizard-submit").click()
    expect(reconnect).to_be_hidden()
    tab.tools_tab.click()
    expect(tab.tool_checkbox("test.value.get")).to_be_checked()
    expect(tab.tool_checkbox("test.value.set")).not_to_be_checked()
    assert _invoke(_ID, "test.value.get")["ok"] is True
    listed = page.request.get(f"{_BASE_URL}/api/integrations").json()["connections"]
    assert sum(record["id"] == _ID for record in listed) == 1
