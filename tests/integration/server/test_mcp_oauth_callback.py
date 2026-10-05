"""Real loopback HTTP tests for the browser-facing MCP callback boundary."""

import asyncio
import logging
import socket
from urllib.parse import urlencode, urlsplit

import aiohttp
import pytest

from server._mcp_oauth_callback import MCPOAuthCallbackError, listen_for_mcp_oauth


STATE = "fixture-oauth-state-not-a-real-secret-12345"


def authorize_url(callback, **overrides):
    params = {
        "state": STATE,
        "redirect_uri": callback.redirect_uri,
        "response_type": "code",
        "code_challenge_method": "S256",
        "code_challenge": "fixture-challenge",
    }
    params.update(overrides)
    return "https://auth.example/authorize?" + urlencode(params)


async def test_early_callback_is_single_use_and_does_not_leak_query(caplog):
    caplog.set_level(logging.INFO, logger="aiohttp.access")
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        params = {"code": "private-fixture-code", "state": STATE, "iss": "https://auth.example"}
        response = await client.get(callback.redirect_uri, params=params)
        assert response.status == 200
        body = await response.text()
        assert "received" in body and "connected" not in body
        assert "private-fixture-code" not in body and STATE not in body
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        # Browser may return before the SDK begins awaiting the response.
        result = await callback.wait_for_result()
        assert (result.code, result.state, result.iss) == (
            "private-fixture-code", STATE, "https://auth.example",
        )
        assert (await client.get(callback.redirect_uri, params=params)).status == 410
        with pytest.raises(MCPOAuthCallbackError, match="No sign-in response"):
            await callback.wait_for_result()
    assert "private-fixture-code" not in caplog.text and STATE not in caplog.text


@pytest.mark.parametrize("params", [
    {"code": "code"},
    {"code": "code", "state": "wrong"},
    {"code": "code", "state": "non-ascii-💥"},
    [("code", "code"), ("state", STATE), ("state", STATE)],
    [("code", "code"), ("code", "other"), ("state", STATE)],
    [("code", "code"), ("iss", "one"), ("iss", "two"), ("state", STATE)],
    {"code": "code", "error": "access_denied", "state": STATE},
    {"code": "code", "error": "", "state": STATE},
    {"code": "", "state": STATE},
    {"error": "", "state": STATE},
    {"state": STATE},
    {"code": "code", "state": STATE, "iss": ""},
])
async def test_invalid_callback_does_not_consume_valid_attempt(params):
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        assert (await client.get(callback.redirect_uri, params=params)).status == 400
        assert (await client.get(callback.redirect_uri, params={"code": "good", "state": STATE})).status == 200
        assert (await callback.wait_for_result()).code == "good"


@pytest.mark.parametrize("error,message", [
    ("access_denied", "Sign-in was declined."),
    ("upstream-error-with-private-details", "The provider could not complete sign-in."),
])
async def test_provider_error_is_sanitized_and_terminal(error, message):
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        response = await client.get(callback.redirect_uri, params={
            "error": error, "error_description": "private description <script>", "state": STATE,
        })
        assert response.status == 200
        body = await response.text()
        assert message in body and "private" not in body and STATE not in body
        with pytest.raises(MCPOAuthCallbackError) as exc:
            await callback.wait_for_result()
        assert str(exc.value) == message
        assert (await client.get(callback.redirect_uri, params={"code": "late", "state": STATE})).status == 410


async def test_cancel_before_and_after_browser_response():
    for receive_first in (False, True):
        async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
            callback.arm(authorize_url(callback))
            if receive_first:
                await client.get(callback.redirect_uri, params={"code": "discard", "state": STATE})
            callback.cancel()
            with pytest.raises(MCPOAuthCallbackError, match="cancelled"):
                await callback.wait_for_result()
            assert (await client.get(callback.redirect_uri, params={"code": "late", "state": STATE})).status == 410


async def test_waiter_cancellation_invalidates_callback():
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        waiter = asyncio.create_task(callback.wait_for_result())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert (await client.get(callback.redirect_uri, params={"code": "late", "state": STATE})).status == 410


async def test_timeout_starts_at_browser_handoff_not_when_waiter_starts():
    async with listen_for_mcp_oauth(timeout=0.01) as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        await asyncio.sleep(0.03)
        assert (await client.get(callback.redirect_uri, params={"code": "late", "state": STATE})).status == 410
        with pytest.raises(MCPOAuthCallbackError, match="timed out"):
            await callback.wait_for_result()


async def test_context_cleanup_wakes_waiter_and_closes_listener():
    async with listen_for_mcp_oauth() as callback:
        callback.arm(authorize_url(callback))
        waiter = asyncio.create_task(callback.wait_for_result())
        await asyncio.sleep(0)
        url = callback.redirect_uri
    with pytest.raises(MCPOAuthCallbackError, match="cancelled"):
        await waiter
    async with aiohttp.ClientSession() as client:
        with pytest.raises(aiohttp.ClientConnectorError):
            await client.get(url)


async def test_wrong_host_and_non_get_do_not_consume_callback():
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        params = {"code": "code", "state": STATE}
        response = await client.get(callback.redirect_uri, params=params, headers={
            "Host": "attacker.example", "Forwarded": "host=localhost",
        })
        assert response.status == 400
        assert (await client.post(callback.redirect_uri, params=params)).status == 405
        assert (await client.head(callback.redirect_uri, params=params)).status == 405
        assert (await client.get(callback.redirect_uri, params=params)).status == 200
        assert (await callback.wait_for_result()).code == "code"


async def test_concurrent_callbacks_only_accept_one():
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        callback.arm(authorize_url(callback))
        responses = await asyncio.gather(*[
            client.get(callback.redirect_uri, params={"code": code, "state": STATE})
            for code in ("one", "two")
        ])
        assert sorted(response.status for response in responses) == [200, 410]
        assert (await callback.wait_for_result()).code in {"one", "two"}


@pytest.mark.parametrize("overrides", [
    {"state": ""}, {"state": "short"}, {"state": "é" * 40},
    {"redirect_uri": "https://attacker.example/callback"},
    {"code_challenge_method": "plain"}, {"code_challenge": ""},
    {"response_type": "token"},
])
async def test_arm_rejects_invalid_sdk_handoff(overrides):
    async with listen_for_mcp_oauth() as callback:
        with pytest.raises(MCPOAuthCallbackError, match="invalid callback configuration"):
            callback.arm(authorize_url(callback, **overrides))


async def test_attempt_cannot_be_rearmed_or_waited_by_two_consumers():
    async with listen_for_mcp_oauth() as callback:
        callback.arm(authorize_url(callback))
        with pytest.raises(MCPOAuthCallbackError, match="cannot be started again"):
            callback.arm(authorize_url(callback))
        waiter = asyncio.create_task(callback.wait_for_result())
        await asyncio.sleep(0)
        with pytest.raises(MCPOAuthCallbackError, match="No sign-in response"):
            await callback.wait_for_result()
        callback.cancel()
        with pytest.raises(MCPOAuthCallbackError, match="cancelled"):
            await waiter


async def test_listener_uses_loopback_and_never_falls_back_from_occupied_port():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises(OSError):
            async with listen_for_mcp_oauth(port=occupied.getsockname()[1]):
                pytest.fail("Must not switch to an unregistered port")
    async with listen_for_mcp_oauth() as callback:
        port = urlsplit(callback.redirect_uri).port
        # A wildcard-bound callback would prevent binding the same port on a
        # different loopback address. Do not touch the machine's real LAN IP.
        with socket.socket() as alternate:
            alternate.bind(("127.0.0.2", port))


async def test_unarmed_or_closed_attempt_cannot_accept_callback():
    async with listen_for_mcp_oauth() as callback, aiohttp.ClientSession() as client:
        assert (await client.get(callback.redirect_uri, params={"code": "early", "state": STATE})).status == 410
        with pytest.raises(MCPOAuthCallbackError, match="No sign-in response"):
            await callback.wait_for_result()
    with pytest.raises(MCPOAuthCallbackError, match="cannot be started again"):
        callback.arm(authorize_url(callback))


@pytest.mark.parametrize("options", [
    {"port": -1}, {"port": 65536}, {"timeout": 0}, {"timeout": -1},
    {"timeout": float("inf")}, {"timeout": float("nan")},
])
async def test_invalid_listener_configuration(options):
    with pytest.raises(ValueError, match="valid loopback port"):
        async with listen_for_mcp_oauth(**options):
            pytest.fail("Invalid listener configuration must not bind a socket")
