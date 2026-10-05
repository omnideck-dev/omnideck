"""Real browser OAuth + app + vault + MCP subprocess, with fake upstream only."""

import asyncio
import json
import os
import threading
from concurrent.futures import Future

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import SettingsPage
from tests.integration.brokering.mcp.fixtures import authorization_server


@pytest.fixture
def remote_service():
    ready = Future()

    def worker():
        async def run():
            async with authorization_server() as state:
                state["mcp"] = True
                stopped = asyncio.Event()
                ready.set_result((state, asyncio.get_running_loop(), stopped))
                await stopped.wait()
        try:
            asyncio.run(run())
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    state, loop, stopped = ready.result(timeout=10)
    try:
        yield state
    finally:
        loop.call_soon_threadsafe(stopped.set)
        thread.join(timeout=10)
        assert not thread.is_alive(), "MCP fixture failed to stop"


def connections(page):
    base = os.environ.get("OMNIDECK_URL", "http://localhost:8080")
    return page.request.get(f"{base}/api/integrations").json()["connections"]


def test_slack_internal_app_setup_guides_registration_without_shared_credentials(page):
    """Exercise the real preset UI without contacting Slack or granting access."""
    before = {item["id"] for item in connections(page)}
    flow = SettingsPage(page).goto_integrations().integrations.open_add_flow()
    flow.pick_provider("slack").next_()
    expect(page.get_by_role("heading", name="Connect Slack", exact=True)).to_be_visible()
    connect_button = page.get_by_role("button", name="Connect", exact=True)
    expect(connect_button).to_be_disabled()
    client_id = page.get_by_label("Slack Client ID", exact=False)
    expect(client_id).to_be_empty()
    expect(page.get_by_label("Server URL", exact=True)).to_have_count(0)
    expect(page.get_by_label("Client Secret", exact=True)).to_have_count(0)
    guide = page.get_by_test_id("slack-app-setup")
    expect(guide.locator("code")).not_to_be_visible()
    guide.locator(":scope > summary").click()
    guide.locator("summary").filter(has_text="Create an internal app").click()
    expect(guide.locator("code")).to_be_visible()
    manifest = json.loads(guide.locator("code").inner_text())
    assert manifest["oauth_config"]["redirect_urls"] == [page.get_by_label("Redirect URL", exact=False).input_value()]
    assert manifest["oauth_config"]["pkce_enabled"] is True
    assert manifest["settings"]["is_mcp_enabled"] is True
    assert "bot" not in manifest["oauth_config"]["scopes"]
    assert "search:read.public" in manifest["oauth_config"]["scopes"]["user"]
    client_id.fill("not-a-client-id")
    expect(connect_button).to_be_disabled()
    client_id.fill("123.456")
    expect(connect_button).to_be_enabled()
    page.get_by_role("button", name="Back", exact=True).click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(flow.root).not_to_be_visible()
    assert {item["id"] for item in connections(page)} == before


def connect(page, remote, label):
    tab = SettingsPage(page).goto_integrations().integrations
    flow = tab.open_add_flow()
    flow.pick_provider("mcp").next_()
    page.get_by_label("Connection name", exact=True).fill(label)
    page.get_by_label("Server URL", exact=True).fill(remote["endpoint"])
    with page.expect_popup(timeout=20_000) as opened:
        page.get_by_role("button", name="Connect", exact=True).click()
    popup = opened.value
    expect(popup.get_by_role("heading", name="Local test service")).to_be_visible()
    return tab, flow, popup


def test_mcp_oauth_tools_and_cancel_cleanup(page, remote_service):
    base = os.environ.get("OMNIDECK_URL", "http://localhost:8080")
    label = "MCP browser fixture"
    integration_id = None
    try:
        tab, flow, popup = connect(page, remote_service, label)
        popup.get_by_role("button", name="Allow test access").click()
        expect(flow.tools_heading).to_be_visible(timeout=20_000)
        record = next(item for item in connections(page) if item["label"] == label)
        integration_id = record["id"]
        assert record["operation_grants"] == []
        assert "fixture-access" not in str(record)
        page.get_by_test_id("integration-tool-mcp.read_value").click()
        flow.next_()
        flow.done.click()
        expect(tab.row(integration_id)).to_be_visible()
        record = next(item for item in connections(page) if item["id"] == integration_id)
        assert record["operation_grants"] == ["mcp.read_value"]
        tab.open_detail(integration_id)
        tab.change_tools_button(integration_id).click()
        expect(tab.tool_checkbox("mcp.read_value")).to_be_checked()
        expect(tab.tool_checkbox("mcp.write_value")).not_to_be_checked()
        tab.tool_checkbox("mcp.read_value").click()
        tab.save_and_wait(integration_id)
        assert next(item for item in connections(page) if item["id"] == integration_id)["operation_grants"] == []
        popup.close()

        _, cancelled, popup = connect(page, remote_service, "Cancelled MCP fixture")
        popup.get_by_role("button", name="Allow test access").click()
        expect(cancelled.tools_heading).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="Cancel", exact=True).click()
        expect(cancelled.root).not_to_be_visible()
        assert not any(item["label"] == "Cancelled MCP fixture" for item in connections(page))
        popup.close()
    finally:
        for record in connections(page):
            if record["label"] in {label, "Cancelled MCP fixture"}:
                page.request.delete(f'{base}/api/integrations/{record["id"]}')


def test_mcp_cancelling_browser_signin_creates_nothing(page, remote_service):
    _, flow, popup = connect(page, remote_service, "Never authorized")
    page.get_by_role("button", name="Exit setup", exact=True).click()
    expect(flow.root).not_to_be_visible()
    popup.get_by_role("button", name="Allow test access").click()
    expect(popup.get_by_text("This sign-in attempt is no longer available.", exact=False)).to_be_visible()
    assert not any(item["label"] == "Never authorized" for item in connections(page))
    assert remote_service["exchanges"] == 0
    popup.close()


def test_mcp_reconnect_discovers_more_tools_without_enabling_them(page, remote_service):
    """The same path upgrades a two-tool Slack connection after broader consent."""
    base = os.environ.get("OMNIDECK_URL", "http://localhost:8080")
    label = "MCP reconnect fixture"
    integration_id = None
    try:
        tab, flow, popup = connect(page, remote_service, label)
        popup.get_by_role("button", name="Allow test access").click()
        expect(flow.tools_heading).to_be_visible(timeout=20_000)
        integration_id = next(item["id"] for item in connections(page) if item["label"] == label)
        tab.tool_checkbox("mcp.read_value").click()
        flow.next_()
        flow.done.click()
        popup.close()
        tab.open_detail(integration_id)
        tab.open_connection_settings()
        tab.reconnect_button(integration_id).click()
        reconnect = page.get_by_test_id("integration-reconnect-flow")
        expect(reconnect).to_be_visible()
        page.get_by_label("Server URL", exact=True).fill(remote_service["endpoint"])
        with page.expect_popup(timeout=20_000) as opened:
            page.get_by_role("button", name="Connect", exact=True).click()
        popup = opened.value
        # The upstream catalog changes during explicit reauthorization. The UI
        # must preserve existing choices without granting the new operation.
        remote_service["tools"].append("search_channels")
        popup.get_by_role("button", name="Allow test access").click()
        expect(reconnect).not_to_be_visible(timeout=20_000)
        records = [item for item in connections(page) if item["label"] == label]
        assert len(records) == 1
        assert records[0]["id"] == integration_id
        assert records[0]["operation_grants"] == ["mcp.read_value"]
        assert "mcp.search_channels" in records[0]["available_operation_ids"]
        tab.change_tools_button(integration_id).click()
        expect(tab.tool_checkbox("mcp.read_value")).to_be_checked()
        expect(tab.tool_checkbox("mcp.search_channels")).not_to_be_checked()
        expect(tab.tool_checkbox("mcp.write_value")).not_to_be_checked()
        tab.tool_checkbox("mcp.search_channels").click()
        tab.save_and_wait(integration_id)
        saved = next(item for item in connections(page) if item["id"] == integration_id)
        assert set(saved["operation_grants"]) == {"mcp.read_value", "mcp.search_channels"}
        popup.close()
    finally:
        if integration_id:
            page.request.delete(f"{base}/api/integrations/{integration_id}")
