"""Shared ownership of consent, commit, cancellation and application shutdown."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest

from server.oauth_setup.adapters.mcp import callback_uri
from server.oauth_setup.coordinator import OAuthSetupCoordinator
from server.oauth_setup.models import NewConnection, PreparedConnection, Reconnect

TARGET = NewConnection("mcp", "Fixture", "fixture", ())
REDIRECT = "http://localhost:9000/callback"


@pytest.mark.parametrize("origin", [
    "ftp://host.test", "https://", "http://localhost:9000/path",
    "http://user@localhost:9000", "http://localhost:9000?x=1", "https://host.test#fragment",
    "https://host.test:bad", "https://host.test:65536", "https://host.test:0",
    "https://host.test:", "https://host.test\n", "https://host.test/\\path",
])
def test_callback_address_rejects_invalid_origins(origin):
    with pytest.raises(ValueError):
        callback_uri(origin)


@pytest.mark.parametrize("origin,expected", [
    ("http://localhost:9000", "http://localhost:9000"),
    ("http://127.0.0.1:9000", "http://127.0.0.1:9000"),
    ("http://llm1:9094/", "http://llm1:9094"),
    ("https://llm1.example.ts.net", "https://llm1.example.ts.net"),
    ("https://app.example.com:8443", "https://app.example.com:8443"),
    ("https://APP.example.com:443/", "https://app.example.com"),
    ("http://app.example.com:80", "http://app.example.com"),
    ("http://[::1]:9094", "http://[::1]:9094"),
])
def test_callback_address_uses_configured_http_or_https_origin(origin, expected):
    assert callback_uri(origin) == expected + "/api/integrations/mcp/oauth/callback"


def ready_adapter():
    return SimpleNamespace(prepare=AsyncMock(return_value=PreparedConnection({"access_token": "not-public"})))


def waiting_adapter():
    async def prepare(browser):
        browser.present("https://fixture.test/authorize?" + urlencode({
            "state": "s" * 32, "redirect_uri": browser.receiver.redirect_uri,
            "response_type": "code", "code_challenge_method": "S256", "code_challenge": "fixture",
        }))
        await browser.receiver.wait_for_result()
        return PreparedConnection({"access_token": "not-public"})
    return SimpleNamespace(prepare=prepare)


async def test_cancel_during_commit_reports_committing_then_definitive_connection():
    entered, release = asyncio.Event(), asyncio.Event()

    async def commit(verb, args):
        entered.set()
        await release.wait()
        assert verb == "add" and args["operation_grants"] == []
        return {"id": "mcp_created"}

    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    pending = await manager.start(ready_adapter(), TARGET, redirect_uri=REDIRECT)
    await entered.wait()
    result = await manager.cancel(pending.handle)
    assert result.status == "committing"
    release.set()
    await pending.task
    assert result.status == "success" and result.integration_id == "mcp_created"
    assert "not-public" not in str(result.public_status())
    await manager.close()


async def test_cancel_waiting_for_consent_never_commits():
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    pending = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
    result = await manager.cancel(pending.handle)
    assert result.status == "cancelled"
    assert pending.browser.receiver.accept(authority="localhost:9000", query_string="state=" + "s" * 32 + "&code=late").status == 410
    commit.assert_not_called()
    await manager.close()


async def test_success_is_visible_before_refresh_and_survives_refresh_failure():
    release = asyncio.Event()
    async def refresh():
        await release.wait()
        raise OSError("secret cache failure")
    manager = OAuthSetupCoordinator(commit=AsyncMock(return_value={"id": "created"}), refresh=refresh)
    pending = await manager.start(ready_adapter(), TARGET, redirect_uri=REDIRECT)
    assert pending.public_status() == {"state": pending.handle, "status": "success", "integration_id": "created"}
    assert (await manager.cancel(pending.handle)).status == "success"
    release.set()
    await pending.task
    assert pending.status == "success" and pending.error is None
    await manager.close()


async def test_shutdown_cancels_consent_but_drains_inflight_commit():
    release = asyncio.Event()
    async def commit(*args):
        await release.wait()
        return {"id": "created"}
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    waiting = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
    saving = await manager.start(ready_adapter(), TARGET, redirect_uri=REDIRECT)
    close = asyncio.create_task(manager.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not close.done()
    assert waiting.status == "cancelled"
    assert saving.status == "committing"
    release.set()
    await close
    assert saving.status == "success"
    with pytest.raises(ValueError, match="shutting down"):
        await manager.start(ready_adapter(), TARGET, redirect_uri=REDIRECT)


async def test_reconnect_preserves_identity_and_does_not_overwrite_approvals():
    commit = AsyncMock(return_value={"id": "existing"})
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    pending = await manager.start(ready_adapter(), Reconnect("existing"), redirect_uri=REDIRECT)
    await pending.task
    commit.assert_awaited_once_with("reconnect", {
        "kind": "integration", "id": "existing", "auth_blob": {"access_token": "not-public"}, "discovered_operations": [],
    })
    await manager.close()


@pytest.mark.parametrize("error,status", [("access_denied", "denied"), ("server_error", "error")])
async def test_provider_error_is_sanitized_and_never_committed(error, status):
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    pending = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
    pending.browser.receiver.accept(authority="localhost:9000", query_string=urlencode({"state": "s" * 32, "error": error, "error_description": "secret"}))
    await pending.task
    assert pending.status == status
    assert "secret" not in str(pending.public_status())
    commit.assert_not_awaited()
    await manager.close()


async def test_expired_consent_never_commits(monkeypatch):
    monkeypatch.setattr("server.oauth_setup.coordinator.INTERACTIVE_TIMEOUT", 0.01)
    commit = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=AsyncMock())
    pending = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
    await pending.task
    assert pending.status == "expired"
    commit.assert_not_awaited()
    await manager.close()


@pytest.mark.parametrize("target,verb", [(TARGET, "add"), (Reconnect("existing"), "reconnect")])
async def test_save_timeout_reports_unknown_outcome_without_expiring_or_retrying(target, verb):
    commit = AsyncMock(side_effect=TimeoutError("private supervisor details"))
    refresh = AsyncMock()
    manager = OAuthSetupCoordinator(commit=commit, refresh=refresh)
    try:
        pending = await manager.start(ready_adapter(), target, redirect_uri=REDIRECT)
        await pending.task
        status = pending.public_status()
        assert status["status"] == "error"
        assert status["error"]["code"] == "SAVE_UNCONFIRMED"
        assert "may have been saved" in status["error"]["message"]
        assert "Check Integrations" in status["error"]["message"]
        assert "private" not in str(status)
        assert "integration_id" not in status
        assert commit.await_count == 1
        assert commit.call_args.args[0] == verb
        refresh.assert_not_awaited()
        assert (await manager.cancel(pending.handle)).public_status() == status
    finally:
        await manager.close()


async def test_setup_managers_do_not_share_attempts():
    first = OAuthSetupCoordinator(commit=AsyncMock(), refresh=AsyncMock())
    second = OAuthSetupCoordinator(commit=AsyncMock(), refresh=AsyncMock())
    pending = await first.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
    assert second.status(pending.handle) is None
    assert second.callback("s" * 32, "/callback") is None
    await first.close()
    await second.close()


@pytest.mark.parametrize("outcome", ["success", "cancelled"])
async def test_finished_attempts_remain_pollable_without_blocking_new_sign_ins(monkeypatch, outcome):
    monkeypatch.setattr("server.oauth_setup.coordinator.MAX_ACTIVE_ATTEMPTS", 2)
    manager = OAuthSetupCoordinator(commit=AsyncMock(return_value={"id": "created"}), refresh=AsyncMock())
    try:
        attempts = []
        for _ in range(4):
            attempt = await manager.start(
                ready_adapter() if outcome == "success" else waiting_adapter(), TARGET, redirect_uri=REDIRECT,
            )
            if outcome == "cancelled":
                await manager.cancel(attempt.handle)
            else:
                await attempt.task
            attempts.append(attempt)
        assert all(manager.status(attempt.handle).status == outcome for attempt in attempts)
    finally:
        await manager.close()


async def test_active_attempt_limit_releases_slot_after_cancellation(monkeypatch):
    monkeypatch.setattr("server.oauth_setup.coordinator.MAX_ACTIVE_ATTEMPTS", 2)
    manager = OAuthSetupCoordinator(commit=AsyncMock(), refresh=AsyncMock())
    try:
        first = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
        await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
        with pytest.raises(ValueError, match="sign-ins in progress"):
            await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
        await manager.cancel(first.handle)
        replacement = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
        assert replacement.status == "pending"
    finally:
        await manager.close()


async def test_finished_result_expires_after_brief_retention_without_removing_active_attempt():
    manager = OAuthSetupCoordinator(commit=AsyncMock(return_value={"id": "created"}), refresh=AsyncMock())
    try:
        finished = await manager.start(ready_adapter(), TARGET, redirect_uri=REDIRECT)
        await finished.task
        active = await manager.start(waiting_adapter(), TARGET, redirect_uri=REDIRECT)
        assert manager.status(finished.handle).integration_id == "created"
        finished.completed_at -= 61
        assert manager.status(finished.handle) is None
        assert manager.status(active.handle).status == "pending"
    finally:
        await manager.close()
