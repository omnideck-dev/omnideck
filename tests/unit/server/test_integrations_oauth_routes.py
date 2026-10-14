from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server import _integrations_oauth_routes as routes
from server._integration_cache import INTEGRATION_CACHE_KEY


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_start_carries_zero_exact_grants_separately_from_scopes() -> None:
    request = MagicMock()
    request.scheme = "http"
    request.host = "127.0.0.1:8080"
    request.json = AsyncMock(
        return_value={
            "slug": "google_workspace",
            "user_suffix": "alice",
            "label": "Google Workspace · alice",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": [
                "openid",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
            "operation_grants": [],
        }
    )
    pending = SimpleNamespace(
        state="state-token",
        authorize_url="https://accounts.example/authorize",
        expires_at=1000,
    )

    with (
        patch.object(routes._oauth, "start", return_value=pending) as start,
        patch("server._integrations_oauth_routes.time.time", return_value=900),
    ):
        response = await routes.handle_start_oauth(request)

    assert response.status == 200
    assert json.loads(response.body)["state"] == "state-token"
    assert start.call_args.kwargs["operation_grants_raw"] == []
    assert "permissions_raw" not in start.call_args.kwargs
    assert start.call_args.kwargs["scopes"] == [
        "openid",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]
    assert start.call_args.kwargs["reconnect_id"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_reconnect_does_not_require_a_new_account_suffix() -> None:
    request = MagicMock()
    request.scheme = "http"
    request.host = "127.0.0.1:8080"
    request.json = AsyncMock(
        return_value={
            "slug": "google_workspace",
            "label": "Google Workspace · alice",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": ["openid"],
            "operation_grants": [],
            "reconnect_id": "google_workspace_alice",
        }
    )
    pending = SimpleNamespace(
        state="state-token",
        authorize_url="https://accounts.example/authorize",
        expires_at=1000,
    )

    with (
        patch.object(routes._oauth, "start", return_value=pending) as start,
        patch("server._integrations_oauth_routes.time.time", return_value=900),
    ):
        response = await routes.handle_start_oauth(request)

    assert response.status == 200
    assert start.call_args.kwargs["user_suffix"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_start_rejects_scopes_outside_the_catalog_policy() -> None:
    request = MagicMock()
    request.scheme = "http"
    request.host = "127.0.0.1:8080"
    request.json = AsyncMock(
        return_value={
            "slug": "google_workspace",
            "user_suffix": "alice",
            "label": "Google Workspace · alice",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": ["https://www.googleapis.com/auth/drive"],
            "operation_grants": [],
        }
    )

    with patch.object(routes._oauth, "start") as start:
        response = await routes.handle_start_oauth(request)

    assert response.status == 400
    assert json.loads(response.body)["error"]["code"] == "BAD_REQUEST"
    start.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_callback_reconnects_existing_connection() -> None:
    request = MagicMock()
    refresh = AsyncMock(return_value=True)
    request.app = {INTEGRATION_CACHE_KEY: MagicMock(refresh=refresh)}
    request.query = {"state": "state-token", "code": "auth-code"}
    pending = SimpleNamespace(
        status="pending",
        reconnect_id="google_workspace_alice",
        slug="google_workspace",
        user_suffix="alice",
        label="Google Workspace · alice",
        operation_grants_raw=[],
    )
    supervisor_result = {
        "id": "google_workspace_alice",
        "slug": "google_workspace",
        "state": "running",
        "operation_grants": ["drive.files.search"],
        "available_operation_ids": ["drive.files.search"],
    }
    supervisor_call = AsyncMock(return_value=supervisor_result)

    with (
        patch.object(routes._oauth, "status", return_value=pending),
        patch.object(
            routes._oauth,
            "fetch_tokens",
            AsyncMock(return_value={"access_token": "token"}),
        ),
        patch.object(routes._oauth, "begin_commit", return_value=True),
        patch.object(routes._oauth, "mark_success") as mark_success,
        patch("server._integrations_oauth_routes._supervisor_call", supervisor_call),
    ):
        response = await routes.handle_oauth_callback(request)

    assert response.status == 200
    supervisor_call.assert_awaited_once_with(
        "reconnect",
        {
            "id": "google_workspace_alice",
            "kind": "integration",
            "auth_blob": {"access_token": "token"},
        },
    )
    mark_success.assert_called_once_with("state-token", "google_workspace_alice")
    refresh.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_cancel_returns_completed_integration_for_ui_cleanup() -> None:
    request = MagicMock()
    request.match_info = {"state": "state-token"}
    pending = SimpleNamespace(
        status="success",
        integration_id="google_workspace_alice",
    )

    with patch.object(routes._oauth, "cancel", return_value=pending) as cancel:
        response = await routes.handle_cancel_oauth(request)

    assert response.status == 200
    assert json.loads(response.body) == {
        "status": "success",
        "integration_id": "google_workspace_alice",
    }
    cancel.assert_called_once_with("state-token")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_callback_does_not_mutate_after_cancellation_wins() -> None:
    request = MagicMock()
    refresh = AsyncMock()
    request.app = {INTEGRATION_CACHE_KEY: MagicMock(refresh=refresh)}
    request.query = {"state": "state-token", "code": "auth-code"}
    pending = SimpleNamespace(
        status="pending",
        reconnect_id=None,
        slug="google_workspace",
        user_suffix="alice",
        label="Google Workspace · alice",
        operation_grants_raw=[],
    )
    with (
        patch.object(routes._oauth, "status", return_value=pending),
        patch.object(
            routes._oauth,
            "fetch_tokens",
            AsyncMock(return_value={"access_token": "token"}),
        ),
        patch.object(routes._oauth, "begin_commit", return_value=False),
        patch("server._integrations_oauth_routes._supervisor_call") as call,
        patch.object(routes._oauth, "mark_success") as mark_success,
    ):
        response = await routes.handle_oauth_callback(request)

    assert response.status == 200
    call.assert_not_awaited()
    refresh.assert_not_awaited()
    mark_success.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oauth_cancel_is_rejected_once_supervisor_commit_starts() -> None:
    request = MagicMock()
    request.match_info = {"state": "state-token"}
    pending = SimpleNamespace(status="committing", integration_id=None)

    with patch.object(routes._oauth, "cancel", return_value=pending):
        response = await routes.handle_cancel_oauth(request)

    assert response.status == 409
    assert json.loads(response.body)["error"]["code"] == "BUSY"
