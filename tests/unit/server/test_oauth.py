from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode, urlsplit, parse_qs

import pytest

from server.oauth_setup.coordinator import OAuthSetupCoordinator
from server.oauth_setup.adapters.google import GoogleOAuthAdapter, build_auth_blob
from server.oauth_setup.models import NewConnection


class _BlockingFlow:
    def __init__(self) -> None:
        self.redirect_uri = ""
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fetch_count = 0
        self.credentials = SimpleNamespace(
            client_id="client-id",
            client_secret="client-secret",
            token="access-token",
            refresh_token="refresh-token",
            token_uri="https://example.test/token",
            scopes=["scope-a"],
            expiry=datetime.now(UTC) + timedelta(hours=1),
        )

    def authorization_url(self, **kwargs):
        return "https://example.test/authorize?" + urlencode({"state": kwargs["state"], "redirect_uri": self.redirect_uri, "response_type": "code", "code_challenge_method": "S256", "code_challenge": "fixture"}), kwargs["state"]

    def fetch_token(self, *, code: str, timeout: int) -> None:
        assert code == "authorization-code"
        assert timeout == 30
        self.fetch_count += 1
        self.entered.set()
        assert self.release.wait(timeout=2)


async def _start(manager, flow):
    with patch("server.oauth_setup.adapters.google.Flow.from_client_config", return_value=flow):
        return await manager.start(GoogleOAuthAdapter("client-id", "client-secret", ["scope-a"]),
            NewConnection("google_workspace", "Google", "alice", ()), redirect_uri="http://127.0.0.1/callback")


def deliver(pending):
    state = parse_qs(urlsplit(pending.browser.authorize_url).query)["state"][0]
    return pending.browser.receiver.accept(authority="127.0.0.1", query_string=urlencode({"state": state, "code": "authorization-code"}))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("granted", "requested", "expected"),
    [
        (["scope-a"], ["scope-a", "scope-b"], "scope-a"),
        ("scope-a", ["scope-a", "scope-b"], "scope-a"),
        (None, ["scope-a"], "scope-a"),
        (None, None, "fallback-scope"),
    ],
)
def test_auth_blob_prefers_granted_scopes_and_falls_back_only_if_absent(granted, requested, expected):
    flow = _BlockingFlow()
    flow.credentials.granted_scopes = granted
    flow.credentials.scopes = requested

    auth_blob = build_auth_blob(flow, fallback_scopes=["fallback-scope"])

    assert auth_blob["scopes"] == expected


@pytest.mark.unit
@pytest.mark.parametrize("granted", [[], ""])
def test_explicitly_empty_granted_scopes_do_not_restore_requested_scopes(granted):
    flow = _BlockingFlow()
    flow.credentials.granted_scopes = granted

    with pytest.raises(ValueError, match="scopes"):
        build_auth_blob(flow, fallback_scopes=["fallback-scope"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_callbacks_exchange_an_authorization_code_once():
    commit = AsyncMock(return_value={"id": "google_alice"})
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    flow = _BlockingFlow()
    pending = await _start(manager, flow)
    try:
        assert deliver(pending).status == 200
        assert await asyncio.to_thread(flow.entered.wait, 1)
        assert deliver(pending).status == 410
    finally:
        flow.release.set()
        await pending.task
        await manager.close()
    assert flow.fetch_count == 1
    assert pending.status == "success"
    commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancellation_wins_while_token_exchange_is_running():
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    flow = _BlockingFlow()
    pending = await _start(manager, flow)
    try:
        deliver(pending)
        assert await asyncio.to_thread(flow.entered.wait, 1)
        assert (await manager.cancel(pending.handle)).status == "cancelled"
    finally:
        flow.release.set()
        await manager.close()
    commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incomplete_token_response_becomes_a_terminal_auth_error():
    manager = OAuthSetupCoordinator(commit=AsyncMock(), refresh=AsyncMock())
    flow = _BlockingFlow()
    flow.credentials.refresh_token = None
    pending = await _start(manager, flow)
    flow.release.set()
    deliver(pending)
    await pending.task
    assert pending.status == "error"
    assert pending.error["code"] == "AUTH"
    await manager.close()
