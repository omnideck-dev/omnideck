from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server._oauth import OAuthIntegrationManager


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

    def authorization_url(self, **_kwargs):
        return "https://example.test/authorize", "ignored-state"

    def fetch_token(self, *, code: str) -> None:
        assert code == "authorization-code"
        self.fetch_count += 1
        self.entered.set()
        assert self.release.wait(timeout=2)


def _start(manager: OAuthIntegrationManager, flow: _BlockingFlow):
    with patch("server._oauth.Flow.from_client_config", return_value=flow):
        return manager.start(
            slug="google_workspace",
            user_suffix="alice",
            label="Google Workspace · alice",
            client_id="client-id",
            client_secret="client-secret",
            scopes=["scope-a"],
            operation_grants_raw=[],
            permissions_raw={},
            reconnect_id=None,
            redirect_uri="http://127.0.0.1/callback",
        )


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

    auth_blob = OAuthIntegrationManager._build_auth_blob(flow, fallback_scopes=["fallback-scope"])

    assert auth_blob["scopes"] == expected


@pytest.mark.unit
@pytest.mark.parametrize("granted", [[], ""])
def test_explicitly_empty_granted_scopes_do_not_restore_requested_scopes(granted):
    flow = _BlockingFlow()
    flow.credentials.granted_scopes = granted

    with pytest.raises(ValueError, match="scopes"):
        OAuthIntegrationManager._build_auth_blob(flow, fallback_scopes=["fallback-scope"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_callbacks_exchange_an_authorization_code_once() -> None:
    manager = OAuthIntegrationManager()
    flow = _BlockingFlow()
    pending = _start(manager, flow)

    first = asyncio.create_task(
        manager.fetch_tokens(
            state=pending.state,
            code="authorization-code",
            error=None,
        )
    )
    assert await asyncio.to_thread(flow.entered.wait, 1)

    duplicate = await manager.fetch_tokens(
        state=pending.state,
        code="authorization-code",
        error=None,
    )
    flow.release.set()
    auth_blob = await first

    assert duplicate is None
    assert auth_blob is not None
    assert flow.fetch_count == 1
    assert manager.begin_commit(pending.state)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancellation_wins_while_token_exchange_is_running() -> None:
    manager = OAuthIntegrationManager()
    flow = _BlockingFlow()
    pending = _start(manager, flow)

    exchange = asyncio.create_task(
        manager.fetch_tokens(
            state=pending.state,
            code="authorization-code",
            error=None,
        )
    )
    assert await asyncio.to_thread(flow.entered.wait, 1)
    assert manager.cancel(pending.state).status == "cancelled"
    flow.release.set()

    assert await exchange is None
    assert not manager.begin_commit(pending.state)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incomplete_token_response_becomes_a_terminal_auth_error() -> None:
    manager = OAuthIntegrationManager()
    flow = _BlockingFlow()
    flow.credentials.refresh_token = None
    pending = _start(manager, flow)
    flow.release.set()

    assert (
        await manager.fetch_tokens(
            state=pending.state,
            code="authorization-code",
            error=None,
        )
        is None
    )
    terminal = manager.status(pending.state)
    assert terminal is not None
    assert terminal.status == "error"
    assert terminal.error_code == "AUTH"
