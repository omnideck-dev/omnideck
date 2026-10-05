"""SDK authorization persistence, restart expiry and refresh side effects."""

import json
import time

import httpx2
import pytest

from brokering.brokers.mcp_broker.authorization import OAuthStorage, PersistentOAuthProvider
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._mcp_refresh import refresh_mcp_authorization
from tests.integration.brokering.mcp.test_sdk_oauth import authorization_server, provider_for  # noqa: F401


@pytest.mark.parametrize("reject_refresh", [False, True])
async def test_restart_restores_expiry_endpoint_and_persists_rotation(authorization_server, monkeypatch, reject_refresh):
    state = authorization_server
    monkeypatch.setenv("OMNIDECK_ENABLE_TEST_INTEGRATIONS", "1")
    storage = OAuthStorage()
    original = provider_for(state, storage)
    provider = PersistentOAuthProvider(
        storage=storage, server_url=state["endpoint"], client_metadata=original.context.client_metadata,
        redirect_handler=original.context.redirect_handler, callback_handler=original.context.callback_handler,
    )
    async with httpx2.AsyncClient(auth=provider, trust_env=False) as client:
        assert (await client.get(state["endpoint"])).status_code == 200
    storage.capture_metadata(provider)
    storage.expires_at = time.time() - 1
    state["accepted_access"] = "renewed-access"
    state["reject_refresh"] = reject_refresh
    fields = BrokerConnectionData({"endpoint": state["endpoint"], "access_token": "fixture-access",
                                   "oauth_state": storage.serialize()})
    saved = []
    if reject_refresh:
        with pytest.raises(ValueError, match="Sign in again"):
            await refresh_mcp_authorization(fields, saved.append)
        assert saved == []
        assert state["refreshes"] == 1 and state["exchanges"] == state["registrations"] == 1
        return
    refreshed = await refresh_mcp_authorization(fields, saved.append)
    assert saved == [refreshed]
    assert refreshed["access_token"] == "renewed-access"
    assert json.loads(refreshed["oauth_state"])["tokens"]["refresh_token"] == "rotated-refresh"
    assert state["refreshes"] == 1 and state["exchanges"] == state["registrations"] == 1
    assert await refresh_mcp_authorization(refreshed, saved.append) is refreshed
    assert len(saved) == 1


async def test_explicit_scope_ceiling_survives_sdk_discovery(authorization_server):
    state = authorization_server
    storage = OAuthStorage()
    original = provider_for(state, storage)
    seen = []

    async def stop_at_redirect(url):
        from urllib.parse import parse_qs, urlsplit
        seen.append(parse_qs(urlsplit(url).query)["scope"])
        raise ValueError("stop before consent")

    provider = PersistentOAuthProvider(
        storage=storage, server_url=state["endpoint"], client_metadata=original.context.client_metadata,
        redirect_handler=stop_at_redirect, callback_handler=original.context.callback_handler,
        requested_scopes="tools.read",
    )
    async with httpx2.AsyncClient(auth=provider, trust_env=False) as client:
        with pytest.raises(ValueError, match="stop before consent"):
            await client.get(state["endpoint"])
    assert seen == [["tools.read"]]
    assert state["exchanges"] == 0
