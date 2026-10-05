"""Internal Slack registration is user supplied; protocol policy is pinned."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from server._mcp_routes import MCP_SETUP_KEY, register_mcp_routes
from integrations.catalog import build_integration_catalog
from integrations.catalog.slack import SLACK_MCP_SCOPES


@pytest.fixture(autouse=True)
def preview_catalog(monkeypatch):
    # The real process builds its catalog once at startup, after reading env.
    monkeypatch.setenv("OMNIDECK_EXTERNAL_URL", "http://localhost:9000")
    monkeypatch.setattr("integrations.catalog._defaults._DEFAULT_INTEGRATIONS", build_integration_catalog())


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OMNIDECK_EXTERNAL_URL", "http://localhost:9000")
    # Even a leftover preview env var must not select a shared registration.
    monkeypatch.setenv("OMNIDECK_SLACK_CLIENT_ID", "old-shared-registration")
    app = web.Application()
    register_mcp_routes(app)
    manager = app[MCP_SETUP_KEY]
    manager.start = AsyncMock(return_value=SimpleNamespace(
        authorize_url="https://slack.com/authorize",
        public_status=lambda: {"state": "mcp_fixture", "status": "pending"},
    ))
    async with TestClient(TestServer(app)) as client:
        yield client, manager


async def test_slack_setup_uses_organization_client_id(client):
    http, manager = client
    response = await http.post("/api/integrations/mcp/oauth/start", json={"slug": "slack", "label": "Work Slack", "client_id": "123.456"})
    assert response.status == 200
    manager.start.assert_awaited_once_with({
        "slug": "slack", "label": "Work Slack", "client_id": "123.456",
        "endpoint": "https://mcp.slack.com/mcp", "issuer": "https://mcp.slack.com",
        "scopes": " ".join(SLACK_MCP_SCOPES),
    })
    settings = await (await http.get("/api/integrations/mcp/connection-settings")).json()
    manifest = settings["slack_manifest"]
    assert manifest["oauth_config"] == {
        "redirect_urls": [settings["redirect_uri"]], "pkce_enabled": True,
        "scopes": {"user": list(SLACK_MCP_SCOPES)},
    }
    assert manifest["settings"]["token_rotation_enabled"] is True
    assert manifest["settings"]["is_mcp_enabled"] is True
    assert "client_secret" not in str(settings)
    assert "client_id" not in settings


def test_slack_scope_policy_covers_the_reviewed_mcp_catalog():
    # Independent expectation: copying the production constant alone would not
    # catch the original two-scope preset regression. No legacy search scope or
    # unrelated administration/bot permissions belong in this policy.
    assert set(SLACK_MCP_SCOPES) == {
        "canvases:read", "canvases:write", "channels:history", "channels:read", "channels:write",
        "chat:write", "emoji:read", "files:read", "files:write",
        "groups:history", "groups:read", "groups:write", "im:history", "im:read", "im:write",
        "lists:read", "lists:write", "mpim:history", "mpim:read", "mpim:write",
        "reactions:read", "reactions:write", "search:read.files", "search:read.im", "search:read.mpim",
        "search:read.private", "search:read.public", "search:read.users", "users:read", "users:read.email",
    }
    assert len(SLACK_MCP_SCOPES) == len(set(SLACK_MCP_SCOPES))


async def test_slack_reconnect_uses_full_preset_without_changing_grants(client, monkeypatch):
    http, manager = client
    monkeypatch.setattr("server._mcp_routes.supervisor_call", AsyncMock(return_value={
        "connections": [{"id": "slack_existing", "slug": "slack", "operation_grants": ["mcp.slack_read_channel"]}],
    }))
    response = await http.post("/api/integrations/mcp/oauth/start", json={
        "slug": "slack", "label": "Work Slack", "reconnect_id": "slack_existing", "client_id": "123.456",
    })
    assert response.status == 200
    settings = manager.start.call_args.args[0]
    assert settings["reconnect_id"] == "slack_existing"
    assert settings["scopes"] == " ".join(SLACK_MCP_SCOPES)
    assert "operation_grants" not in settings


@pytest.mark.parametrize("field,value", [
    ("client_secret", "not-accepted"), ("endpoint", "https://other.test/mcp"),
    ("issuer", "https://other.test"), ("scopes", "chat:write"),
])
async def test_browser_cannot_override_slack_registration(client, field, value):
    http, manager = client
    response = await http.post("/api/integrations/mcp/oauth/start", json={"slug": "slack", "label": "Work", field: value})
    assert response.status == 400
    manager.start.assert_not_awaited()


@pytest.mark.parametrize("client_id", ["", "xoxb-not-a-client-id", "https://wrong.test", "12.34\n56", "abc.def"])
async def test_missing_or_invalid_client_id_cannot_fall_back_to_shared_registration(client, client_id):
    http, manager = client
    response = await http.post("/api/integrations/mcp/oauth/start", json={
        "slug": "slack", "label": "Work", "client_id": client_id,
    })
    assert response.status == 400
    assert "Client ID" in (await response.json())["error"]["message"]
    manager.start.assert_not_awaited()


async def test_reconnect_settings_come_from_supervisor(client, monkeypatch):
    http, _ = client
    lookup = AsyncMock(return_value={"endpoint": "https://mcp.slack.com/mcp", "client_id": "123.456", "issuer": "https://mcp.slack.com"})
    monkeypatch.setattr("server._mcp_routes.supervisor_call", lookup)
    response = await http.get("/api/integrations/mcp/connection-settings?connection_id=slack_existing")
    assert response.status == 200
    assert (await response.json())["connection"]["client_id"] == "123.456"
    lookup.assert_awaited_once_with("mcp_setup_settings", {"id": "slack_existing"})


async def test_reconnect_settings_failure_is_not_a_silent_reset(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr("server._mcp_routes.supervisor_call", AsyncMock(side_effect=RuntimeError("secret details")))
    response = await http.get("/api/integrations/mcp/connection-settings?connection_id=slack_existing")
    assert response.status >= 400
    assert "secret details" not in await response.text()
