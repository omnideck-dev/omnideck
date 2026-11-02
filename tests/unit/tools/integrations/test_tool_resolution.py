"""Exact operation grants control agent-tool exposure."""

import pytest

from integrations.operations import OPERATIONS_BY_GROUP
from tools.integrations._tool_resolution import (
    _BUILDERS,
    connection_tools,
)
from integrations.connection_cache import IntegrationConnection


def _integration(*operations: str, state: str = "running") -> IntegrationConnection:
    return IntegrationConnection(
        id="acct-1",
        slug="acct",
        operation_grants=frozenset(operations),
        state=state,
    )


def _names(tools) -> set[str]:
    # The suffix identifies the bound account/operation, not the operation name.
    return {tool.__name__.rsplit("_", 1)[0] for tool in tools}


@pytest.mark.unit
@pytest.mark.parametrize("operation_id", sorted(_BUILDERS))
def test_agent_tools_expose_the_bound_connection_not_a_routing_parameter(operation_id: str) -> None:
    tool = connection_tools(_integration(operation_id))[0]
    definition = tool.definition()["function"]
    assert "Connection: acct." in definition["description"]
    assert "integration_id" not in definition["parameters"]["properties"]
    assert "integration_id" not in definition["parameters"].get("required", [])


@pytest.mark.unit
def test_one_grant_exposes_only_its_agent_tool() -> None:
    names = _names(connection_tools(_integration("email.messages.search")))
    assert names == {"search_email"}


@pytest.mark.unit
def test_every_calendar_operation_has_an_independent_tool() -> None:
    names = _names(connection_tools(_integration(*OPERATIONS_BY_GROUP["calendar"])))
    assert names == {
        "list_calendars", "list_events", "search_events", "create_event",
        "update_event", "delete_event", "update_event_series", "delete_event_series",
    }


@pytest.mark.unit
def test_absent_grants_yield_no_tools() -> None:
    assert connection_tools(_integration()) == []


@pytest.mark.unit
def test_non_running_integration_is_ignored() -> None:
    assert connection_tools(_integration("email.messages.send", state="auth_failed")) == []


@pytest.mark.unit
def test_same_operation_can_be_granted_per_instance() -> None:
    records = [
        IntegrationConnection(id="allowed", slug="gmail", operation_grants=frozenset({"email.messages.send"})),
        IntegrationConnection(id="denied", slug="gmail", operation_grants=frozenset()),
    ]
    assert _names(connection_tools(records[0])) == {"send_email"}
    assert connection_tools(records[1]) == []


@pytest.mark.unit
def test_http_is_one_indivisible_operation() -> None:
    assert _names(connection_tools(_integration("http.request"))) == {"call_api"}


@pytest.mark.unit
def test_non_integration_connections_do_not_expose_tools() -> None:
    from dataclasses import replace

    assert connection_tools(replace(_integration("email.messages.search"), kind="provider")) == []
