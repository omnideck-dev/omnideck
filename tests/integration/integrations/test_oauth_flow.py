"""OAuth over real HTTP, including token refresh in the Google broker process.

Only the external authorization/token endpoints and local storage paths are
substituted. The Google OAuth library, callback state machine, supervisor RPC,
credential encryption, scope mapping, and broker startup are production code.
"""

import asyncio
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering import broker_client
from integrations.catalog import integration_catalog
from brokering.supervisor._store import enc_path, list_connection_ids, read_raw_meta
from server import _oauth

READ = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY = "https://www.googleapis.com/auth/gmail.modify"
ID = "google_workspace_local"


@pytest.fixture
async def oauth_provider(monkeypatch):
    state = {
        "scopes": [READ, MODIFY],
        "calls": [],
        "reject_refresh": False,
        "deny": False,
        "pause_exchange": False,
        "entered": asyncio.Event(),
        "release": asyncio.Event(),
    }

    async def authorize(request):
        query = {"state": request.query["state"]}
        query.update({"error": "access_denied"} if state["deny"] else {"code": "local-code"})
        raise web.HTTPFound(request.query["redirect_uri"] + "?" + urlencode(query))

    async def token(request):
        body = await request.post()
        state["calls"].append(body["grant_type"])
        if body["grant_type"] == "authorization_code":
            assert body["code"] == "local-code"
            if state["pause_exchange"]:
                state["entered"].set()
                await asyncio.wait_for(state["release"].wait(), timeout=10)
        else:
            assert body["refresh_token"] == "local-refresh"
            if state["reject_refresh"]:
                return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response(
            {
                "access_token": "local-access",
                "refresh_token": "local-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": " ".join(state["scopes"]),
            }
        )

    app = web.Application()
    app.router.add_get("/authorize", authorize)
    app.router.add_post("/token", token)
    async with TestServer(app) as server:
        monkeypatch.setenv("OAUTHLIB_INSECURE_TRANSPORT", "1")
        monkeypatch.setattr(_oauth, "_AUTH_URI", str(server.make_url("/authorize")))
        monkeypatch.setattr(_oauth, "_TOKEN_URI", str(server.make_url("/token")))
        yield state


async def authorize(client, *, reconnect=False):
    body = {
        "slug": "google_workspace",
        "label": "Local Google",
        "client_id": "local-client",
        "client_secret": "local-secret",
        "scopes": [READ, MODIFY],
        "operation_grants": [],
    }
    body.update({"reconnect_id": ID} if reconnect else {"user_suffix": "local"})
    started = await client.post("/api/integrations/oauth/start", json=body)
    assert started.status == 200, await started.text()
    flow = await started.json()
    # Follow the external redirect back through the real callback HTTP route.
    response = await client.session.get(flow["authorize_url"])
    await response.read()
    status = await client.get(f"/api/integrations/oauth/status/{flow['state']}")
    return await status.json()


async def test_oauth_reconnect_updates_choices_without_revoking_saved_grants(integration_app, oauth_provider):
    async with integration_app(integration_catalog()) as h:
        assert (await authorize(h.client))["status"] == "success"
        proc = h.supervisor._registry.get(ID).broker.proc
        listed = await (await h.client.get("/api/integrations")).json()
        record = listed["connections"][0]
        assert record["id"] == ID
        assert record["operation_grants"] == []
        assert "email.messages.send" in record["available_operation_ids"]
        saved = await h.client.patch(
            f"/api/integrations/{ID}",
            json={
                "operation_grants": ["email.messages.get", "email.messages.send"],
            },
        )
        assert saved.status == 200, await saved.text()

        # Consent grants only READ even though the reconnect requested both.
        oauth_provider["scopes"] = [READ]
        assert (await authorize(h.client, reconnect=True))["status"] == "success"
        assert h.supervisor._registry.get(ID).broker.proc is proc
        listed = await (await h.client.get("/api/integrations")).json()
        assert len(listed["connections"]) == 1
        record = listed["connections"][0]
        assert record["id"] == ID
        assert "email.messages.send" not in record["available_operation_ids"]
        selected = ["email.messages.get", "email.messages.send"]
        assert record["operation_grants"] == selected
        assert read_raw_meta(h.supervisor.vault_dir, ID)["agent_operation_grants"] == selected
        assert "email.messages.send" not in {op["id"] for op in record["operations"]}
        # Reaches argument validation, proving the broker received the saved
        # send grant. Empty args avoid any request to Google's actual API.
        with pytest.raises(broker_client.IntegrationError, match="BAD_REQUEST"):
            await broker_client.call(ID, "email.messages.send", {}, app_sock_path=h.supervisor.app_sock_path)
        # Explicit configuration still accepts only scope-available choices.
        saved = await h.client.patch(
            f"/api/integrations/{ID}", json={"operation_grants": selected},
        )
        assert saved.status == 200, await saved.text()
        assert (await saved.json())["operation_grants"] == ["email.messages.get"]
        with pytest.raises(broker_client.IntegrationPermissionDenied):
            await broker_client.call(ID, "email.messages.send", {}, app_sock_path=h.supervisor.app_sock_path)
        assert oauth_provider["calls"].count("authorization_code") == 2
        # Only initial connection and reconnect refresh tokens; grant edits do not.
        assert oauth_provider["calls"].count("refresh_token") == 2


async def test_rejected_refresh_keeps_active_google_broker_and_saved_credentials(integration_app, oauth_provider):
    async with integration_app(integration_catalog()) as h:
        assert (await authorize(h.client))["status"] == "success"
        record = h.supervisor._registry.get(ID)
        proc = record.broker.proc
        encrypted = enc_path(h.supervisor.vault_dir, ID).read_bytes()
        oauth_provider["reject_refresh"] = True
        status = await authorize(h.client, reconnect=True)
        assert status["status"] == "error"
        assert status["error"]["code"] == "AUTH"
        assert record.broker.proc is proc
        assert record.state == "running"
        assert enc_path(h.supervisor.vault_dir, ID).read_bytes() == encrypted
        oauth_provider["reject_refresh"] = False
        assert (await authorize(h.client, reconnect=True))["status"] == "success"
        assert record.broker.proc is proc


@pytest.mark.parametrize("failure", ["deny", "reject_refresh"])
async def test_oauth_failure_leaves_no_registered_or_persisted_connection(
    integration_app,
    oauth_provider,
    failure,
):
    oauth_provider[failure] = True
    async with integration_app(integration_catalog()) as h:
        status = await authorize(h.client)
        assert status["status"] == ("denied" if failure == "deny" else "error")
        if failure == "reject_refresh":
            assert status["error"]["code"] == "AUTH"
        assert (await (await h.client.get("/api/integrations")).json())["connections"] == []
        assert list_connection_ids(h.supervisor.vault_dir) == []


async def test_cancel_during_real_token_exchange_prevents_late_registration(integration_app, oauth_provider):
    oauth_provider["pause_exchange"] = True
    async with integration_app(integration_catalog()) as h:
        response = await h.client.post(
            "/api/integrations/oauth/start",
            json={
                "slug": "google_workspace",
                "label": "Local Google",
                "user_suffix": "local",
                "client_id": "local-client",
                "client_secret": "local-secret",
                "scopes": [READ, MODIFY],
                "operation_grants": [],
            },
        )
        assert response.status == 200
        flow = await response.json()
        callback = asyncio.create_task(h.client.session.get(flow["authorize_url"]))
        try:
            await asyncio.wait_for(oauth_provider["entered"].wait(), timeout=5)
            cancelled = await h.client.delete(f"/api/integrations/oauth/status/{flow['state']}")
            assert (await cancelled.json())["status"] == "cancelled"
        finally:
            oauth_provider["release"].set()
            completed = await asyncio.wait_for(callback, timeout=5)
            await completed.read()
        assert (await (await h.client.get("/api/integrations")).json())["connections"] == []
        assert list_connection_ids(h.supervisor.vault_dir) == []
        assert oauth_provider["calls"] == ["authorization_code"]
