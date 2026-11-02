"""Provider request policy stays separate from shared setup ownership."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.oauth_setup import google_routes, routes
from server.oauth_setup.models import NewConnection, Reconnect


def request_for(body):
    request = MagicMock()
    request.scheme, request.host = "http", "127.0.0.1:8080"
    request.json = AsyncMock(return_value=body)
    pending = SimpleNamespace(browser=SimpleNamespace(authorize_url="https://accounts.example/authorize"),
                              public_status=lambda: {"state": "oauth_attempt", "status": "pending"})
    manager = SimpleNamespace(start=AsyncMock(return_value=pending))
    request.app = {routes.SETUP_KEY: manager}
    return request, manager


def google_settings():
    return {"slug": "google_workspace", "user_suffix": "alice", "label": "Google Workspace · alice",
            "client_id": "client-id", "client_secret": "client-secret",
            "scopes": ["openid", "https://www.googleapis.com/auth/gmail.readonly"], "operation_grants": []}


async def test_oauth_start_carries_zero_exact_grants_separately_from_scopes():
    request, manager = request_for(google_settings())
    response = await google_routes.start(request)
    assert response.status == 200
    assert json.loads(response.body)["state"] == "oauth_attempt"
    adapter, target = manager.start.call_args.args
    assert adapter.scopes == google_settings()["scopes"]
    assert target == NewConnection("google_workspace", "Google Workspace · alice", "alice", ())
    assert manager.start.call_args.kwargs["redirect_uri"] == "http://127.0.0.1:8080/api/integrations/oauth/callback"


async def test_oauth_reconnect_does_not_require_a_new_account_suffix():
    settings = google_settings()
    settings.pop("user_suffix")
    settings["reconnect_id"] = "google_workspace_alice"
    request, manager = request_for(settings)
    assert (await google_routes.start(request)).status == 200
    assert manager.start.call_args.args[1] == Reconnect("google_workspace_alice")


async def test_oauth_start_rejects_scopes_outside_the_catalog_policy():
    settings = {**google_settings(), "scopes": ["https://www.googleapis.com/auth/drive"]}
    request, manager = request_for(settings)
    response = await google_routes.start(request)
    assert response.status == 400
    assert json.loads(response.body)["error"]["code"] == "BAD_REQUEST"
    manager.start.assert_not_called()


@pytest.mark.parametrize("status,expected", [("success", 200), ("committing", 409)])
async def test_oauth_cancel_does_not_lose_a_committing_or_completed_connection(status, expected):
    request = MagicMock()
    request.match_info = {"state": "oauth_attempt"}
    body = {"status": status, "integration_id": "google_workspace_alice" if status == "success" else None}
    pending = SimpleNamespace(status=status, public_status=lambda: body)
    cancel = AsyncMock(return_value=pending)
    request.app = {routes.SETUP_KEY: SimpleNamespace(cancel=cancel)}
    response = await routes.cancel(request)
    assert response.status == expected
    if expected == 200:
        assert json.loads(response.body) == body
    else:
        assert json.loads(response.body)["error"]["code"] == "BUSY"
    cancel.assert_awaited_once_with("oauth_attempt")
