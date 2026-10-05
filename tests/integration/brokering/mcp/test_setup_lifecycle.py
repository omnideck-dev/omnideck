"""OAuth browser callback -> real supervisor/vault -> isolated MCP process."""

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from brokering.brokers.mcp_broker.catalog import MCP_DRIVER
from brokering.supervisor._lifecycle import Supervisor
from brokering.supervisor._store import read_secrets, write_secrets
from brokering.connection_data import BrokerConnectionData
from integrations.catalog import IntegrationCatalogEntry
from integrations.catalog.slack import SLACK_MCP_SCOPES
from integrations.service import IntegrationService
from server._mcp_setup import MCPSetupManager
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call
from tests.integration.brokering.mcp.test_sdk_oauth import authorization_server  # noqa: F401


@pytest.mark.parametrize("slug", ["mcp", "slack"])
async def test_setup_select_call_revoke_restart_and_remove(authorization_server, tmp_path, monkeypatch, slug):
    state = authorization_server
    state["mcp"] = True
    if slug == "slack":
        state["preregistered"] = True
        state["auth_methods"] = ["client_secret_post"]
    monkeypatch.setenv("OMNIDECK_ENABLE_TEST_INTEGRATIONS", "1")
    sup = Supervisor(
        vault_dir=tmp_path / "vault", app_sock_path=tmp_path / "app.sock", sockets_dir=tmp_path / "sockets",
        host_paths={}, catalog={slug: IntegrationCatalogEntry(slug, "MCP", "", "Custom", MCP_DRIVER)},
    )
    await sup.start()

    async def commit(verb, args):
        response = await _rpc_call(sup.app_sock_path, verb, args)
        assert "error" not in response, response
        return response["result"]

    manager = None

    async def callback(request):
        receiver = manager.callback(request.query["state"])
        return await receiver.handle_callback(request)

    app = web.Application()
    app.router.add_get("/api/integrations/mcp/oauth/callback", callback)
    try:
        async with TestServer(app) as server:
            manager = MCPSetupManager(callback_origin=f"http://localhost:{server.port}", commit=commit, allow_loopback=True)
            settings = {"slug": slug, "label": "Fixture", "endpoint": state["endpoint"]}
            if slug == "slack":
                settings.update(client_id="preregistered-slack-fixture", issuer=state["origin"],
                                scopes=" ".join(SLACK_MCP_SCOPES))
            pending = await manager.start(settings)
            state["authorization"] = parse_qs(urlsplit(pending.authorize_url).query)
            assert state["authorization"]["code_challenge_method"] == ["S256"]
            if slug == "slack":
                assert state["authorization"]["scope"] == [" ".join(SLACK_MCP_SCOPES)]
                assert state["registrations"] == 0
            async with httpx2.AsyncClient(trust_env=False) as browser:
                response = await browser.get(manager.redirect_uri, params={
                    "code": "fixture-code", "state": state["authorization"]["state"][0], "iss": state["origin"],
                })
                assert response.status_code == 200
            await asyncio.wait_for(pending.task, 15)
            assert pending.status == "success"
            records = (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"]
            record = records[0]
            assert record["operation_grants"] == []
            assert record["available_operation_ids"] == ["mcp.read_value", "mcp.write_value"]
            assert "fixture-access" not in json.dumps(record)
            public_settings = (await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]}))["result"]
            assert public_settings == {
                "endpoint": state["endpoint"], "issuer": state["origin"],
                "client_id": "preregistered-slack-fixture" if slug == "slack" else "fixture-client",
            }
            assert "fixture-access" not in json.dumps(public_settings)
            assert "fixture-refresh" not in json.dumps(public_settings)
            socket = Path(record["socket"])
            denied = await _rpc_call(socket, "mcp.read_value", {})
            assert denied["error"]["code"] == "PERMISSION_DENIED"
            assert state["calls"] == []
            await _rpc_call(sup.app_sock_path, "update", {"id": record["id"], "operation_grants": ["mcp.read_value"]})
            result = await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path)
            assert result["content"][0]["text"] == "fixture value"
            await sup.stop()
            state["tools"].append("new_tool")
            await sup.start()
            restored = (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"][0]
            assert (await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]}))["result"] == public_settings
            assert restored["operation_grants"] == ["mcp.read_value"]
            assert (await _rpc_call(Path(restored["socket"]), "mcp.new_tool", {}))["error"]["code"] == "PERMISSION_DENIED"
            # Reauthorize through the real setup coordinator, not a fabricated
            # replacement blob. New discoveries must never become grants.
            reconnect = await manager.start({**settings, "reconnect_id": record["id"]})
            state["authorization"] = parse_qs(urlsplit(reconnect.authorize_url).query)
            if slug == "slack":
                assert state["authorization"]["scope"] == [" ".join(SLACK_MCP_SCOPES)]
            async with httpx2.AsyncClient(trust_env=False) as browser:
                response = await browser.get(manager.redirect_uri, params={
                    "code": "fixture-code", "state": state["authorization"]["state"][0], "iss": state["origin"],
                })
                assert response.status_code == 200
            await asyncio.wait_for(reconnect.task, 15)
            assert reconnect.status == "success"
            assert reconnect.integration_id == record["id"]
            reconnected = (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"]
            assert len(reconnected) == 1
            assert reconnected[0]["operation_grants"] == ["mcp.read_value"]
            assert "mcp.new_tool" in reconnected[0]["available_operation_ids"]
            assert (await _rpc_call(Path(restored["socket"]), "mcp.new_tool", {}))["error"]["code"] == "PERMISSION_DENIED"
            assert (await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path))["content"]
            # Expiry after startup takes the real serialized supervisor refresh
            # path and private credential handoff, not an SDK-only mock.
            saved = dict(read_secrets(sup.vault_dir, record["id"], sup._manager._master_key))
            oauth = json.loads(saved["oauth_state"])
            oauth["expires_at"] = time.time() - 1
            saved["oauth_state"] = json.dumps(oauth)
            write_secrets(sup.vault_dir, record["id"], sup._manager._master_key, BrokerConnectionData(saved))
            state["accepted_access"] = "renewed-access"
            assert (await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path))["content"]
            rotated = read_secrets(sup.vault_dir, record["id"], sup._manager._master_key)
            assert rotated["access_token"] == "renewed-access"
            assert json.loads(rotated["oauth_state"])["tokens"]["refresh_token"] == "rotated-refresh"
            assert state["refreshes"] == 1
            await _rpc_call(sup.app_sock_path, "update", {"id": record["id"], "operation_grants": []})
            assert (await _rpc_call(Path(restored["socket"]), "mcp.read_value", {}))["error"]["code"] == "PERMISSION_DENIED"
            # A damaged registration must not leak the serialized credential
            # bundle or offer a silently reset reconnect form.
            damaged = {**dict(rotated), "oauth_state": "secret-invalid-json"}
            write_secrets(sup.vault_dir, record["id"], sup._manager._master_key, BrokerConnectionData(damaged))
            rejected = await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]})
            assert rejected["error"]["code"] == "AUTH"
            assert "secret-invalid-json" not in json.dumps(rejected)
            await _rpc_call(sup.app_sock_path, "remove", {"id": record["id"]})
            assert (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"] == []
            removed = await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]})
            assert removed["error"]["code"] == "NOT_FOUND"
    finally:
        if manager:
            await manager.close()
        await sup.stop()
