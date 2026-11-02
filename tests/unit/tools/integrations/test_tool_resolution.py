"""Exact operation grants control agent-tool exposure."""

import pytest

from integrations.operations import OPERATIONS_BY_GROUP
from tools.integrations._tool_resolution import (
    _BUILDERS,
    _ids_granting,
    _tools_for_category,
    integration_tools_by_category,
)
from integrations.connection_cache import IntegrationConnection


def _integration(*operations: str, state: str = "running") -> list[IntegrationConnection]:
    return [IntegrationConnection(
        id="acct-1",
        slug="acct",
        operation_grants=frozenset(operations),
        state=state,
    )]


def _names(tools) -> set[str]:
    return {tool.__name__ for tool in tools}


@pytest.mark.unit
@pytest.mark.parametrize("operation_id", sorted(_BUILDERS))
def test_agent_tool_descriptions_use_integration_id_consistently(operation_id: str) -> None:
    tool = _BUILDERS[operation_id](["acct-1"])
    doc = tool.__doc__ or ""
    assert "Valid integration IDs: 'acct-1'." in doc
    parameter_doc = next(line for line in doc.splitlines() if line.strip().startswith("integration_id:"))
    assert "integration" in parameter_doc.split(":", 1)[1]
    assert "connection" not in doc.lower()


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
        IntegrationConnection(id="allowed", slug="gmail", operation_grants=frozenset({"email.messages.send"})),
        IntegrationConnection(id="denied", slug="gmail", operation_grants=frozenset()),
    ]
    assert _ids_granting("email.messages.send", records) == frozenset({"allowed"})


@pytest.mark.unit
def test_http_is_one_indivisible_operation() -> None:
    assert _names(_tools_for_category("http", _integration("http.request"))) == {"call_api"}


@pytest.mark.unit
def test_by_category_uses_snapshot_and_reports_state() -> None:
    by_category = integration_tools_by_category(tuple(_integration("email.messages.search")))
    assert by_category["email"].available is True
    assert _names(by_category["email"].tools) == {"search_email"}
    assert by_category["calendar"].available is False
    assert by_category["calendar"].tools == []
