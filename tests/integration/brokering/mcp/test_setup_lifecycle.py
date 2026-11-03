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
from brokering.supervisor._store import read_raw_meta, read_secrets, write_secrets
from brokering.connection_data import BrokerConnectionData
from integrations.catalog import IntegrationCatalogEntry
from integrations.catalog.slack import SLACK_MCP_SCOPES
from integrations.service import IntegrationService
from server.oauth_setup.coordinator import OAuthSetupCoordinator
from server.oauth_setup.adapters.mcp import MCPOAuthAdapter
from server.oauth_setup.models import NewConnection, Reconnect
from server.oauth_setup.routes import receive_callback
from unittest.mock import AsyncMock
from tests.integration.brokering.supervisor.test_supervisor import _rpc_call
from tests.integration.brokering.mcp.test_sdk_oauth import authorization_server  # noqa: F401


@pytest.mark.parametrize("slug,scopes", [("mcp", ""), ("mcp", "tools.read"), ("slack", " ".join(SLACK_MCP_SCOPES))])
async def test_setup_select_call_revoke_restart_and_remove(authorization_server, tmp_path, monkeypatch, slug, scopes):
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
        receiver = manager.callback(request.query["state"], request.path)
        return receive_callback(receiver, request)

    app = web.Application()
    app.router.add_get("/api/integrations/mcp/oauth/callback", callback)
    try:
        async with TestServer(app) as server:
            manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock(return_value=True))
            redirect_uri = f"http://localhost:{server.port}/api/integrations/mcp/oauth/callback"
            settings = {"slug": slug, "label": "Fixture", "endpoint": state["endpoint"], "scopes": scopes}
            if slug == "slack":
                settings.update(client_id="preregistered-slack-fixture", issuer=state["origin"],
                                scopes=" ".join(SLACK_MCP_SCOPES))
            pending = await manager.start(MCPOAuthAdapter(settings), NewConnection(slug, "Fixture", "fixture", ()), redirect_uri=redirect_uri)
            state["authorization"] = parse_qs(urlsplit(pending.browser.authorize_url).query)
            assert state["authorization"]["code_challenge_method"] == ["S256"]
            assert state["authorization"]["scope"] == [scopes or "tools"]
            if slug == "slack":
                assert state["authorization"]["scope"] == [" ".join(SLACK_MCP_SCOPES)]
                assert state["registrations"] == 0
            async with httpx2.AsyncClient(trust_env=False) as browser:
                response = await browser.get(redirect_uri, params={
                    "code": "fixture-code", "state": state["authorization"]["state"][0], "iss": state["origin"],
                })
                assert response.status_code == 200
            await asyncio.wait_for(pending.task, 15)
            assert pending.status == "success", pending.public_status()
            records = (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"]
            record = records[0]
            assert record["operation_grants"] == []
            assert record["available_operation_ids"] == ["mcp.read_value", "mcp.write_value"]
            disk_meta = read_raw_meta(sup.vault_dir, record["id"])
            assert [tool["id"] for tool in disk_meta["discovered_operations"]] == record["available_operation_ids"]
            assert "fixture-access" not in json.dumps(disk_meta) and "fixture-refresh" not in json.dumps(disk_meta)
            credentials = read_secrets(sup.vault_dir, record["id"], sup._manager._master_key)
            assert "discovered_operations" not in credentials
            assert "discovered_operations_digest" in credentials
            assert "fixture-access" not in json.dumps(record)
            public_settings = (await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]}))["result"]
            assert public_settings == {
                "endpoint": state["endpoint"], "issuer": state["origin"],
                "client_id": "preregistered-slack-fixture" if slug == "slack" else "fixture-client",
                "scopes": scopes,
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
            # Restart directly from the current persisted catalog and credentials.
            state["tools"].append("new_tool")
            await sup.start()
            restored = (await _rpc_call(sup.app_sock_path, "list", {}))["result"]["connections"][0]
            assert (await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]}))["result"] == public_settings
            assert restored["operation_grants"] == ["mcp.read_value"]
            assert (await _rpc_call(Path(restored["socket"]), "mcp.new_tool", {}))["error"]["code"] == "PERMISSION_DENIED"
            # Reauthorize through the real setup coordinator, not a fabricated
            # replacement blob. New discoveries must never become grants.
            reconnect = await manager.start(MCPOAuthAdapter({**public_settings, "slug": slug, "label": "Fixture"}), Reconnect(record["id"]), redirect_uri=redirect_uri)
            state["authorization"] = parse_qs(urlsplit(reconnect.browser.authorize_url).query)
            assert state["authorization"]["scope"] == [scopes or "tools"]
            if slug == "slack":
                assert state["authorization"]["scope"] == [" ".join(SLACK_MCP_SCOPES)]
            async with httpx2.AsyncClient(trust_env=False) as browser:
                response = await browser.get(redirect_uri, params={
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
            disk_meta = read_raw_meta(sup.vault_dir, record["id"])
            assert "mcp.new_tool" in {tool["id"] for tool in disk_meta["discovered_operations"]}
            assert disk_meta["agent_operation_grants"] == ["mcp.read_value"]
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
            assert "discovered_operations" not in rotated
            assert read_raw_meta(sup.vault_dir, record["id"])["discovered_operations"] == disk_meta["discovered_operations"]
            assert json.loads(rotated["oauth_state"])["tokens"]["refresh_token"] == "rotated-refresh"
            assert state["refreshes"] == 1
            # A revoked token with no known expiry must renew through the same
            # supervisor path, without replaying the rejected tool call.
            saved = dict(rotated)
            oauth = json.loads(saved["oauth_state"])
            oauth["expires_at"] = None
            saved["oauth_state"] = json.dumps(oauth)
            write_secrets(sup.vault_dir, record["id"], sup._manager._master_key, BrokerConnectionData(saved))
            state["accepted_access"] = "renewed-again"
            from brokering.broker_client import IntegrationError
            calls_before = list(state["calls"])
            with pytest.raises(IntegrationError, match="Authorization was renewed"):
                await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path)
            assert state["calls"] == calls_before
            assert state["refreshes"] == 2
            assert (await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path))["content"]
            await sup.stop()
            state["accepted_access"] = "renewed-on-restart"
            await sup.start()
            assert state["refreshes"] == 3
            assert (await IntegrationService().invoke(record["id"], "mcp.read_value", {}, app_sock_path=sup.app_sock_path))["content"]
            assert (await _rpc_call(sup.app_sock_path, "mcp_setup_settings", {"id": record["id"]}))["result"] == public_settings
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


@pytest.mark.parametrize("outcome", ["denied", "cancelled"])
async def test_mcp_setup_preserves_consent_outcome_through_sdk_transport(authorization_server, outcome):
    state = authorization_server
    state["mcp"] = True
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    try:
        pending = await manager.start(MCPOAuthAdapter({"endpoint": state["endpoint"]}),
            NewConnection("mcp", "Fixture", "fixture", ()), redirect_uri="http://localhost:9000/callback")
        if outcome == "cancelled":
            await manager.cancel(pending.handle)
        else:
            from urllib.parse import urlencode
            oauth_state = parse_qs(urlsplit(pending.browser.authorize_url).query)["state"][0]
            pending.browser.receiver.accept(authority="localhost:9000", query_string=urlencode({
                "state": oauth_state, "error": "access_denied", "error_description": "private-provider-detail",
            }))
            await asyncio.wait_for(pending.task, 5)
        assert pending.status == outcome, pending.public_status()
        assert "private-provider-detail" not in str(pending.public_status())
        commit.assert_not_awaited()
    finally:
        await manager.close()


async def test_local_mcp_setup_without_oauth_or_test_mode(monkeypatch):
    from mcp.server import MCPServer
    from tests.integration.brokering.mcp.test_sdk_transport import serve_sdk

    monkeypatch.delenv("OMNIDECK_ENABLE_TEST_INTEGRATIONS", raising=False)
    server = MCPServer("Local unauthenticated fixture")

    @server.tool()
    def local_status() -> str:
        """Return the local service status."""
        return "ready"

    commit = AsyncMock(return_value={"id": "local"})
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock(return_value=True))
    try:
        async with serve_sdk(server) as endpoint:
            pending = await manager.start(
                MCPOAuthAdapter({"endpoint": endpoint}),
                NewConnection("mcp", "Local", "local", ()),
                redirect_uri="http://localhost:9000/api/integrations/mcp/oauth/callback",
            )
            await asyncio.wait_for(pending.task, 10)
            assert pending.status == "success", pending.public_status()
            assert not pending.browser.authorize_url
            commit.assert_awaited_once()
            fields = commit.call_args.args[1]["auth_blob"]
            assert fields["access_token"] == ""
    finally:
        await manager.close()
