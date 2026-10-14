from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from brokering import broker_client, supervisor_client
from integrations.service import IntegrationService


@pytest.fixture(params=["list_connections", "invoke"])
def service_call(request, monkeypatch):
    """Exercise the same failure contract at both transport boundaries."""
    method = request.param
    client = supervisor_client if method == "list_connections" else broker_client

    async def run(error):
        async def fail(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(client, "call", fail)
        service = IntegrationService()
        if method == "list_connections":
            return await service.list_connections(app_sock_path="/tmp/app.sock")
        return await service.invoke(
            "gmail_work", "email.messages.search", {},
            app_sock_path="/tmp/app.sock",
        )

    return run


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [
    FileNotFoundError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError, TimeoutError, OSError,
])
async def test_service_wraps_transport_errors_with_original_cause(service_call, error_type) -> None:
    error = error_type("transport failed")
    with pytest.raises(broker_client.IntegrationError, match="transport failed") as caught:
        await service_call(error)
    assert caught.value.__cause__ is error


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [
    asyncio.CancelledError,
    broker_client.IntegrationNotConnected,
    broker_client.IntegrationAuthFailed,
    broker_client.IntegrationPermissionDenied,
])
async def test_service_preserves_cancellation_and_domain_errors(service_call, error_type) -> None:
    error = error_type("unchanged")
    with pytest.raises(error_type) as caught:
        await service_call(error)
    assert caught.value is error


@pytest.mark.asyncio
async def test_invoke_passes_canonical_operation_to_broker_unchanged(monkeypatch) -> None:
    captured = {}

    async def _call(connection_id, verb, arguments, *, app_sock_path):
        captured.update(
            {
                "connection_id": connection_id,
                "verb": verb,
                "arguments": arguments,
                "app_sock_path": app_sock_path,
            }
        )
        return {"headers": []}

    monkeypatch.setattr(broker_client, "call", _call)
    result = await IntegrationService().invoke(
        "gmail_work",
        "email.messages.search",
        {"folder": "INBOX", "query": "invoice"},
        app_sock_path=Path("/tmp/app.sock"),
    )
    assert result == {"headers": []}
    assert captured["verb"] == "email.messages.search"
    assert captured["connection_id"] == "gmail_work"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_id", ["email.future", "search_messages"])
async def test_unknown_operation_is_rejected_before_transport(monkeypatch, operation_id) -> None:
    called = False

    async def _call(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(broker_client, "call", _call)
    with pytest.raises(broker_client.IntegrationError, match="unknown integration operation"):
        await IntegrationService().invoke(
            "gmail_work",
            operation_id,
            {},
            app_sock_path="/tmp/app.sock",
        )
    assert called is False


@pytest.mark.asyncio
async def test_list_connections_requests_only_integrations(monkeypatch) -> None:
    connection = {
        "id": "gmail_work",
        "kind": "integration",
        "state": "auth_failed",
        "operation_grants": ["email.messages.search"],
        "available_operation_ids": ["email.messages.search", "email.messages.send"],
        "operations": [
            {"id": "email.messages.search", "title": "Search email"},
            {"id": "email.messages.send", "title": "Send email"},
        ],
    }

    async def _call(verb, args, *, app_sock_path):
        assert verb == "list"
        assert args == {"kind": "integration"}
        return {"connections": [connection]}

    monkeypatch.setattr(supervisor_client, "call", _call)
    assert await IntegrationService().list_connections(
        app_sock_path="/tmp/app.sock",
    ) == [connection]


@pytest.mark.asyncio
async def test_list_connections_returns_a_snapshot(monkeypatch) -> None:
    connections = [{"id": "gmail_work", "kind": "integration"}]

    async def _call(*_args, **_kwargs):
        return {"connections": connections}

    monkeypatch.setattr(supervisor_client, "call", _call)
    result = await IntegrationService().list_connections(app_sock_path="/tmp/app.sock")
    assert result == connections
    assert result is not connections


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    None, [], {}, {"integrations": []}, {"connections": None},
    {"connections": {}}, {"connections": "bad"}, {"connections": [None]},
])
async def test_list_connections_rejects_malformed_supervisor_data(monkeypatch, response) -> None:
    async def _call(*_args, **_kwargs):
        return response

    monkeypatch.setattr(supervisor_client, "call", _call)
    with pytest.raises(broker_client.IntegrationError, match="integration list response"):
        await IntegrationService().list_connections(app_sock_path="/tmp/app.sock")


@pytest.mark.asyncio
async def test_empty_connections_do_not_fall_back_to_legacy_data(monkeypatch) -> None:
    async def _call(*_args, **_kwargs):
        return {"connections": [], "integrations": [{"id": "stale"}]}

    monkeypatch.setattr(supervisor_client, "call", _call)
    assert await IntegrationService().list_connections(app_sock_path="/tmp/app.sock") == []
