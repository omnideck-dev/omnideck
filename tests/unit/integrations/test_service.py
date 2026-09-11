from __future__ import annotations

from pathlib import Path

import pytest

from integrations import broker_client, supervisor_client
from integrations.service import AGENT_CONTEXT, IntegrationService, InvocationContext


@pytest.mark.asyncio
async def test_invoke_passes_canonical_operation_to_broker_unchanged(monkeypatch) -> None:
    captured = {}

    async def _call(instance_id, verb, arguments, *, app_sock_path):
        captured.update(
            {
                "instance_id": instance_id,
                "verb": verb,
                "arguments": arguments,
                "app_sock_path": app_sock_path,
            }
        )
        return {"headers": []}

    monkeypatch.setattr(broker_client, "call", _call)
    result = await IntegrationService().invoke(
        AGENT_CONTEXT,
        "gmail_work",
        "email.messages.search",
        {"folder": "INBOX", "query": "invoice"},
        app_sock_path=Path("/tmp/app.sock"),
    )
    assert result == {"headers": []}
    assert captured["verb"] == "email.messages.search"
    assert captured["instance_id"] == "gmail_work"


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
            AGENT_CONTEXT,
            "gmail_work",
            operation_id,
            {},
            app_sock_path="/tmp/app.sock",
        )
    assert called is False


@pytest.mark.asyncio
async def test_custom_app_context_denies_until_app_specific_grants_exist() -> None:
    with pytest.raises(broker_client.IntegrationPermissionDenied):
        await IntegrationService().invoke(
            InvocationContext(consumer="custom_app", consumer_id="crm"),
            "gmail_work",
            "email.messages.search",
            {},
            app_sock_path="/tmp/app.sock",
        )


@pytest.mark.asyncio
async def test_list_operations_returns_structured_grant_state(monkeypatch) -> None:
    async def _call(verb, args, *, app_sock_path):
        assert verb == "resolve"
        return {
            "kind": "integration",
            "operation_grants": ["email.messages.search"],
            "operations": [
                {"id": "email.messages.search", "title": "Search email"},
                {"id": "email.messages.send", "title": "Send email"},
            ],
        }

    monkeypatch.setattr(supervisor_client, "call", _call)
    operations = await IntegrationService().list_operations(
        AGENT_CONTEXT,
        "gmail_work",
        app_sock_path="/tmp/app.sock",
    )
    assert operations == [
        {"id": "email.messages.search", "title": "Search email", "granted": True},
        {"id": "email.messages.send", "title": "Send email", "granted": False},
    ]


@pytest.mark.asyncio
async def test_list_instances_requests_only_integrations(monkeypatch) -> None:
    async def _call(verb, args, *, app_sock_path):
        assert verb == "list"
        assert args == {"kind": "integration"}
        return {"connections": [{"id": "gmail_work", "kind": "integration"}]}

    monkeypatch.setattr(supervisor_client, "call", _call)
    assert await IntegrationService().list_instances(
        AGENT_CONTEXT,
        app_sock_path="/tmp/app.sock",
    ) == [{"id": "gmail_work", "kind": "integration"}]
