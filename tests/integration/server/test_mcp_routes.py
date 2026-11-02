"""Internal Slack registration is user supplied; protocol policy is pinned."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode, urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from server.oauth_setup.routes import SETUP_KEY, register_oauth_routes
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
    register_oauth_routes(app)
    manager = app[SETUP_KEY]
    manager.start = AsyncMock(return_value=SimpleNamespace(
        browser=SimpleNamespace(authorize_url="https://slack.com/authorize"),
        public_status=lambda: {"state": "mcp_fixture", "status": "pending"},
    ))
    async with TestClient(TestServer(app)) as client:
        yield client, manager


async def test_slack_setup_uses_organization_client_id(client):
    http, manager = client
    response = await http.post("/api/integrations/mcp/oauth/start", json={"slug": "slack", "label": "Work Slack", "client_id": "123.456"})
    assert response.status == 200
    assert manager.start.call_args.args[0].settings == {
        "slug": "slack", "label": "Work Slack", "client_id": "123.456",
        "endpoint": "https://mcp.slack.com/mcp", "issuer": "https://mcp.slack.com",
        "scopes": " ".join(SLACK_MCP_SCOPES),
    }
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
    monkeypatch.setattr("server.oauth_setup.mcp_routes.supervisor_call", AsyncMock(return_value={
        "connections": [{"id": "slack_existing", "slug": "slack", "operation_grants": ["mcp.slack_read_channel"]}],
    }))
    response = await http.post("/api/integrations/mcp/oauth/start", json={
        "slug": "slack", "label": "Work Slack", "reconnect_id": "slack_existing", "client_id": "123.456",
    })
    assert response.status == 200
    settings = manager.start.call_args.args[0].settings
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
    monkeypatch.setattr("server.oauth_setup.mcp_routes.supervisor_call", lookup)
    response = await http.get("/api/integrations/mcp/connection-settings?connection_id=slack_existing")
    assert response.status == 200
    assert (await response.json())["connection"]["client_id"] == "123.456"
    lookup.assert_awaited_once_with("mcp_setup_settings", {"id": "slack_existing"})


async def test_reconnect_settings_failure_is_not_a_silent_reset(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr("server.oauth_setup.mcp_routes.supervisor_call", AsyncMock(side_effect=RuntimeError("secret details")))
    response = await http.get("/api/integrations/mcp/connection-settings?connection_id=slack_existing")
    assert response.status >= 400
    assert "secret details" not in await response.text()


@pytest.mark.parametrize("origin", ["http://llm1:9094", "https://llm1.example.ts.net"])
async def test_configured_remote_callback_completes_setup_and_rejects_wrong_host_and_replay(monkeypatch, origin):
    from server.oauth_setup.coordinator import OAuthSetupCoordinator
    from server.oauth_setup.models import PreparedConnection

    monkeypatch.setenv("OMNIDECK_EXTERNAL_URL", origin)
    redirect_uri = origin + "/api/integrations/mcp/oauth/callback"
    state = "fixture-public-origin-oauth-state-123456789"

    async def prepare(browser):
        assert browser.receiver.redirect_uri == redirect_uri
        browser.present("https://provider.example/authorize?" + urlencode({
            "state": state, "redirect_uri": redirect_uri, "response_type": "code",
            "code_challenge_method": "S256", "code_challenge": "fixture-challenge",
        }))
        response = await browser.receiver.wait_for_result()
        assert response.code == "fixture-code"
        return PreparedConnection({"access_token": "private-fixture-token"})

    monkeypatch.setattr("server.oauth_setup.mcp_routes.MCPOAuthAdapter", lambda settings: SimpleNamespace(prepare=prepare))
    app = web.Application()
    register_oauth_routes(app)
    commit = AsyncMock(return_value={"id": "saved"})
    app[SETUP_KEY] = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    async with TestClient(TestServer(app)) as http:
        # A proxy's forwarded headers or an arbitrary Host cannot select the
        # redirect. The configured public origin is used throughout setup.
        headers = {"Host": "other.example", "X-Forwarded-Host": "other.example", "X-Forwarded-Proto": "http"}
        settings = await (await http.get("/api/integrations/mcp/connection-settings", headers=headers)).json()
        assert settings["redirect_uri"] == redirect_uri
        assert settings["slack_manifest"]["oauth_config"]["redirect_urls"] == [redirect_uri]
        started = await http.post("/api/integrations/mcp/oauth/start", headers=headers, json={
            "slug": "mcp", "label": "Remote", "endpoint": "https://provider.example/mcp",
        })
        assert started.status == 200
        pending = app[SETUP_KEY].status((await started.json())["state"])
        path = urlsplit(redirect_uri).path
        params = {"state": state, "code": "fixture-code"}
        assert (await http.get(path, params=params, headers=headers)).status == 400
        public_host = {"Host": urlsplit(origin).netloc}
        assert (await http.get(path, params={**params, "state": "wrong"}, headers=public_host)).status == 410
        assert (await http.get(path, params=params, headers=public_host)).status == 200
        await pending.task
        status = await (await http.get(f"/api/integrations/mcp/oauth/status/{pending.handle}")).json()
        assert status["status"] == "success" and status["integration_id"] == "saved"
        assert "private-fixture-token" not in str(status)
        commit.assert_awaited_once()
        assert (await http.get(path, params=params, headers=public_host)).status == 410
