"""Supervisor-owned MCP refresh; the broker never receives refresh tokens."""

import asyncio
from collections.abc import Callable

from brokering.connection_data import BrokerConnectionData
from brokering.brokers.mcp_broker.authorization import OAuthStorage, PersistentOAuthProvider
from brokering.brokers.mcp_broker._network import mcp_http_client
from integrations.catalog import test_integrations_enabled


async def refresh_mcp_authorization(
    fields: BrokerConnectionData, persist: Callable[[BrokerConnectionData], None],
) -> BrokerConnectionData:
    """Persist rotation immediately; never roll it back if broker startup fails."""
    result = fields

    def save(raw: str, access_token: str) -> None:
        nonlocal result
        result = BrokerConnectionData({**fields, "oauth_state": raw, "access_token": access_token})
        persist(result)

    storage = OAuthStorage(fields.get("oauth_state", ""), persist=save)
    if not storage.needs_refresh():
        return fields
    if storage.client_info is None or storage.metadata is None:
        raise ValueError("Sign in again to restore authorization.")
    endpoint = fields["endpoint"]
    provider = PersistentOAuthProvider(
        server_url=endpoint, storage=storage, client_metadata=storage.client_info,
    )
    async with asyncio.timeout(30):
        async with mcp_http_client(
            auth=provider, allow_loopback=test_integrations_enabled(), background_resource=endpoint,
            resource_endpoint=endpoint,
        ) as http:
            # OAuth runs before this harmless protocol request. A legacy server
            # may reject discovery; only token refresh is relevant here. Never
            # replay a tools/call as the trigger for refreshing credentials.
            await http.post(endpoint, json={"jsonrpc": "2.0", "id": "refresh", "method": "server/discover"}, headers={
                "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
            })
    if storage.needs_refresh() or result is fields:
        raise ValueError("Sign in again to restore authorization.")
    return result
