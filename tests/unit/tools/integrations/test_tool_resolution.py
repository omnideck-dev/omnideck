"""Exact operation grants control agent-tool exposure."""

import pytest

from integrations.operations import OPERATIONS_BY_GROUP
from tools.integrations._tool_resolution import (
    _ids_granting,
    _tools_for_category,
    integration_tools_by_category,
)
from tools.integrations.types import RegisteredIntegration


def _integration(*operations: str, state: str = "running") -> list[RegisteredIntegration]:
    return [RegisteredIntegration(
        id="acct-1",
        slug="acct",
        operation_grants=frozenset(operations),
        state=state,
    )]


def _names(tools) -> set[str]:
    return {tool.__name__ for tool in tools}


@pytest.mark.unit
def test_one_grant_exposes_only_its_agent_tool() -> None:
    names = _names(_tools_for_category(
        "email", _integration("email.messages.search"),
    ))
    assert names == {"search_email"}


@pytest.mark.unit
def test_every_calendar_operation_has_an_independent_tool() -> None:
    names = _names(_tools_for_category(
        "calendar", _integration(*OPERATIONS_BY_GROUP["calendar"]),
    ))
    assert names == {
        "list_calendars", "list_events", "search_events", "create_event",
        "update_event", "delete_event", "update_event_series", "delete_event_series",
    }


@pytest.mark.unit
def test_absent_grants_yield_no_tools() -> None:
    assert _tools_for_category("email", _integration("calendar.events.list")) == []
    assert _tools_for_category("email", []) == []


@pytest.mark.unit
def test_non_running_integration_is_ignored() -> None:
    assert _tools_for_category(
        "email", _integration("email.messages.send", state="auth_failed"),
    ) == []


@pytest.mark.unit
def test_same_operation_can_be_granted_per_instance() -> None:
    records = [
        RegisteredIntegration(id="allowed", slug="gmail", operation_grants=frozenset({"email.messages.send"})),
        RegisteredIntegration(id="denied", slug="gmail", operation_grants=frozenset()),
    ]
    assert _ids_granting("email.messages.send", records) == frozenset({"allowed"})


@pytest.mark.unit
def test_http_is_one_indivisible_operation() -> None:
    assert _names(_tools_for_category("http", _integration("http.request"))) == {"call_api"}


@pytest.mark.unit
async def test_by_category_snapshots_registry_and_reports_state(monkeypatch) -> None:
    async def _registry():
        return {"acct-1": _integration("email.messages.search")[0]}

    monkeypatch.setattr("tools.integrations._tool_resolution.registered_integrations", _registry)
    by_category = await integration_tools_by_category()
    assert by_category["email"].available is True
    assert _names(by_category["email"].tools) == {"search_email"}
    assert by_category["calendar"].available is False
    assert by_category["calendar"].tools == []
