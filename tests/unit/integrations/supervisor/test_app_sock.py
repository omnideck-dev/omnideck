"""Tests for supervisor app-socket wire serialization."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from integrations._rpc import RpcError
from integrations.supervisor._app_sock import AppSockHandler, _record_to_dict
from integrations.supervisor._registry import BrokeredConnectionRecord, Registry
from integrations.supervisor.types import IntegrationMeta, ModelProviderMeta
from integrations.operations import OPERATIONS_BY_GROUP


def _record(meta, available=frozenset()) -> BrokeredConnectionRecord:
    broker = MagicMock()
    broker.socket_path = "/run/cvault/example.sock"
    return BrokeredConnectionRecord(meta=meta, broker=broker, available_operations=available)


@pytest.mark.unit
def test_model_provider_has_no_integration_operation_policy() -> None:
    now = datetime.now(UTC)
    result = _record_to_dict(_record(ModelProviderMeta(
        id="llm_openai", slug="llm_openai", label="OpenAI", added_at=now, updated_at=now,
    )))
    assert result["kind"] == "model_provider"
    assert "operation_grants" not in result
    assert "permissions" not in result


@pytest.mark.unit
def test_integration_serializes_operations_and_legacy_projection() -> None:
    now = datetime.now(UTC)
    available = OPERATIONS_BY_GROUP["email"]
    result = _record_to_dict(_record(IntegrationMeta(
        id="gmail_alice",
        slug="gmail",
        label="Gmail",
        agent_operation_grants=frozenset({"email.messages.search"}),
        added_at=now,
        updated_at=now,
    ), available))

    assert result["kind"] == "integration"
    assert result["operation_grants"] == ["email.messages.search"]
    assert "email.messages.search" in result["available_operation_ids"]
    assert "email.messages.send" in result["available_operation_ids"]
    # The custom subset cannot be represented safely in the old UI.
    assert result["permissions"] == {"email": "off"}
    assert {operation["id"] for operation in result["operations"]} == available


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "code"),
    [("auth_failed", "AUTH"), ("broken", "UNAVAILABLE")],
)
def test_resolve_rejects_non_running_broker(state: str, code: str) -> None:
    now = datetime.now(UTC)
    record = _record(IntegrationMeta(
        id="gmail_alice",
        slug="gmail",
        label="Gmail",
        added_at=now,
        updated_at=now,
    ))
    record.state = state
    registry = Registry()
    registry.add(record)
    handler = AppSockHandler(manager=MagicMock(), registry=registry)

    with pytest.raises(RpcError) as raised:
        handler._resolve({"id": "gmail_alice"})

    assert raised.value.code == code


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_rejects_non_string_user_suffix_at_rpc_boundary() -> None:
    handler = AppSockHandler(manager=MagicMock(), registry=Registry())

    with pytest.raises(RpcError) as raised:
        await handler._add({
            "slug": "gmail",
            "user_suffix": 42,
            "label": "Gmail",
            "auth_blob": {},
            "operation_grants": [],
        })

    assert raised.value.code == "BAD_REQUEST"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_rejects_invalid_legacy_permission_values_as_bad_request() -> None:
    handler = AppSockHandler(manager=MagicMock(), registry=Registry())

    with pytest.raises(RpcError) as raised:
        await handler._add({
            "slug": "gmail",
            "user_suffix": "alice",
            "label": "Gmail",
            "auth_blob": {},
            "permissions": {"email": "invalid"},
        })

    assert raised.value.code == "BAD_REQUEST"
