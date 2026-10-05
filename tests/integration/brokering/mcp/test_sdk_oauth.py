"""Pin the OAuth SDK contract using a disposable HTTP authorization server.

Only the upstream provider and browser callback are fixtures. Discovery, DCR,
PKCE, state/issuer validation and token exchange run through the real SDK.
Memory storage here is deliberately not the future production vault adapter.
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, OAuthFlowError
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from server._mcp_oauth_callback import listen_for_mcp_oauth
from tests.integration.brokering.mcp.fixtures import authorization_server as run_authorization_server


@dataclass
class MemoryTokenStorage:
    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        self.client_info = client_info


@pytest.fixture
async def authorization_server():
    async with run_authorization_server() as state:
        yield state


def provider_for(state, storage, invalid_callback=None, receiver=None):
    async def redirect(url):
        parsed = urlsplit(url)
        assert f"{parsed.scheme}://{parsed.netloc}" == state["origin"]
        query = parse_qs(parsed.query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["resource"] == [state["endpoint"]]
        assert query["scope"] == ["tools"]
        state["authorization"] = query
        if receiver is not None:
            receiver.arm(url)
            async with httpx2.AsyncClient(trust_env=False) as browser:
                response = await browser.get(receiver.redirect_uri, params={
                    "code": "fixture-code", "state": query["state"][0],
                    "iss": "https://wrong-issuer.example" if invalid_callback == "issuer" else state["origin"],
                })
                assert response.status_code == 200

    async def callback():
        if receiver is not None:
            return await receiver.wait_for_result()
        return AuthorizationCodeResult(
            code="fixture-code",
            state="wrong-state" if invalid_callback == "state" else state["authorization"]["state"][0],
            iss="https://wrong-issuer.example" if invalid_callback == "issuer" else state["origin"],
        )

    return OAuthClientProvider(
        server_url=state["endpoint"],
        client_metadata=OAuthClientMetadata(
            client_name="omnideck compatibility fixture",
            redirect_uris=[AnyUrl(receiver.redirect_uri if receiver else "http://127.0.0.1:43210/callback")],
            token_endpoint_auth_method="none",
            scope="tools",
        ),
        storage=storage,
        redirect_handler=redirect,
        callback_handler=callback,
        client_metadata_url="https://client.example/oauth/metadata.json" if state["cimd"] else None,
    )


@pytest.mark.parametrize("cimd", [False, True])
async def test_discovery_registration_pkce_and_stored_token_reuse(authorization_server, cimd):
    state = authorization_server
    state["cimd"] = cimd
    storage = MemoryTokenStorage()
    # A new provider instance models reconnecting with persisted SDK state.
    for _ in range(2):
        async with httpx2.AsyncClient(auth=provider_for(state, storage), timeout=5, trust_env=False) as client:
            response = await client.get(state["endpoint"])
            assert response.status_code == 200
    assert state["registrations"] == (0 if cimd else 1)
    assert state["exchanges"] == 1
    assert storage.tokens.refresh_token == "fixture-refresh"
    expected_client = "https://client.example/oauth/metadata.json" if cimd else "fixture-client"
    assert storage.client_info.client_id == expected_client


async def test_expired_token_refresh_persists_rotated_token(authorization_server):
    state = authorization_server
    state["expires_in"] = 1
    storage = MemoryTokenStorage()
    auth = provider_for(state, storage)
    async with httpx2.AsyncClient(auth=auth, timeout=5, trust_env=False) as client:
        assert (await client.get(state["endpoint"])).status_code == 200
        state["accepted_access"] = "renewed-access"
        # Expire the issued token without changing SDK internals or wall-clock
        # functions used by the HTTP server and other concurrently running tests.
        await asyncio.sleep(1.1)
        assert (await client.get(state["endpoint"])).status_code == 200
    assert state["refreshes"] == 1
    assert state["exchanges"] == state["registrations"] == 1
    assert storage.tokens.refresh_token == "rotated-refresh"


@pytest.mark.parametrize("invalid_callback", ["state", "issuer"])
async def test_callback_mismatch_prevents_token_exchange(authorization_server, invalid_callback):
    state = authorization_server
    storage = MemoryTokenStorage()
    auth = provider_for(state, storage, invalid_callback)
    async with httpx2.AsyncClient(auth=auth, timeout=5, trust_env=False) as client:
        with pytest.raises(OAuthFlowError):
            await client.get(state["endpoint"])
    assert state["exchanges"] == 0
    assert storage.tokens is None


@pytest.mark.parametrize("invalid_issuer", [False, True])
@pytest.mark.parametrize("auth_methods", [["none"], ["client_secret_post"]])
async def test_preregistered_client_uses_real_loopback_callback(authorization_server, invalid_issuer, auth_methods):
    """No DCR, real browser HTTP callback, SDK PKCE and issuer validation."""
    state = authorization_server
    state["preregistered"] = True
    state["auth_methods"] = auth_methods
    async with listen_for_mcp_oauth() as receiver:
        storage = MemoryTokenStorage(client_info=OAuthClientInformationFull(
            client_id="preregistered-fixture", issuer=state["origin"],
            redirect_uris=[AnyUrl(receiver.redirect_uri)], token_endpoint_auth_method="none",
        ))
        auth = provider_for(state, storage, "issuer" if invalid_issuer else None, receiver)
        async with httpx2.AsyncClient(auth=auth, timeout=5, trust_env=False) as client:
            if invalid_issuer:
                with pytest.raises(OAuthFlowError):
                    await client.get(state["endpoint"])
                assert state["exchanges"] == 0
                assert storage.tokens is None
            else:
                assert (await client.get(state["endpoint"])).status_code == 200
                assert state["exchanges"] == 1
                assert storage.tokens.access_token == "fixture-access"
        assert state["registrations"] == 0
