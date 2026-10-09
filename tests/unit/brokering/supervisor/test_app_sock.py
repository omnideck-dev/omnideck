"""Tests for supervisor app-socket wire serialization."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from brokering._rpc import RpcError
from brokering.connection_data import BrokerConnectionData
from brokering.supervisor._app_sock import AppSockHandler, _parse_connection_data, _record_to_dict
from brokering.supervisor._registry import BrokeredConnectionRecord, Registry
from brokering.supervisor.types import IntegrationConnectionMeta, ModelProviderConnectionMeta
from integrations.operations import OPERATIONS_BY_GROUP


def _record(meta, available=frozenset()) -> BrokeredConnectionRecord:
    broker = MagicMock()
    broker.socket_path = "/run/cvault/example.sock"
    return BrokeredConnectionRecord(meta=meta, broker=broker, available_operations=available)


def test_list_uses_connections_envelope_for_both_domains():
    now = datetime.now(UTC)
    registry = Registry()
    for meta in (
        IntegrationConnectionMeta(id="gmail_work", slug="gmail", label="Work", added_at=now, updated_at=now),
        ModelProviderConnectionMeta(id="llm_openai", slug="llm_openai", label="OpenAI", added_at=now, updated_at=now),
    ):
        registry.add(_record(meta))
    handler = AppSockHandler(manager=MagicMock(), registry=registry)
    result = handler._list({})
    assert set(result) == {"connections"}
    assert {item["kind"] for item in result["connections"]} == {"integration", "model_provider"}
    for kind in ("integration", "model_provider"):
        filtered = handler._list({"kind": kind})
        assert set(filtered) == {"connections"}
        assert [item["kind"] for item in filtered["connections"]] == [kind]


def test_wire_credentials_are_converted_to_auth_data():
    auth = _parse_connection_data({"token": "secret", "scopes": "scope-a"})
    assert isinstance(auth, BrokerConnectionData)
    assert auth.granted_scopes == frozenset({"scope-a"})


@pytest.mark.parametrize("verb", ["add", "update"])
@pytest.mark.parametrize("legacy", [{"permissions": {"email": "rw"}}, {"write_allowed": True}])
async def test_old_policy_requests_require_refresh_without_calling_manager(verb, legacy):
    manager = MagicMock()
    handler = AppSockHandler(manager=manager, registry=Registry())
    with pytest.raises(RpcError, match="This screen is out of date.*Refresh the app, then try again") as raised:
        await handler.handle(verb, {"id": "gmail_example", **legacy})
    assert raised.value.code == "BAD_REQUEST"
    manager.add.assert_not_called()
    manager.update.assert_not_called()


@pytest.mark.parametrize("verb", ["add", "reconnect"])
@pytest.mark.parametrize("auth_blob", [None, [], {"token": None}, {"token": {"secret": "value"}}])
async def test_invalid_authentication_never_reaches_manager(verb, auth_blob):
    manager = MagicMock()
    handler = AppSockHandler(manager=manager, registry=Registry())
    with pytest.raises(RpcError) as caught:
        await handler.handle(verb, {"id": "http_test", "auth_blob": auth_blob})
    assert caught.value.code == "BAD_REQUEST"
    manager.add.assert_not_called()
    manager.reconnect.assert_not_called()


@pytest.mark.unit
def test_model_provider_has_no_integration_operation_policy() -> None:
    now = datetime.now(UTC)
    result = _record_to_dict(_record(ModelProviderConnectionMeta(
        id="llm_openai", slug="llm_openai", label="OpenAI", added_at=now, updated_at=now,
    )))
    assert result["kind"] == "model_provider"
    assert "operation_grants" not in result
    assert "permissions" not in result


@pytest.mark.unit
def test_integration_serializes_only_operation_policy() -> None:
    now = datetime.now(UTC)
    available = OPERATIONS_BY_GROUP["email"]
    result = _record_to_dict(_record(IntegrationConnectionMeta(
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
    assert not {"permissions", "max_access", "capabilities"} & result.keys()
    assert {operation["id"] for operation in result["operations"]} == available


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "code"),
    [("auth_failed", "AUTH"), ("broken", "UNAVAILABLE")],
)
def test_resolve_rejects_non_running_broker(state: str, code: str) -> None:
    now = datetime.now(UTC)
    record = _record(IntegrationConnectionMeta(
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
