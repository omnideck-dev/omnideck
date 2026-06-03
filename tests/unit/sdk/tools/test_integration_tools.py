"""Unit tests for the integration tool helper.

``integration_tools_for(capability, records)`` is the single place that maps a
permissioned integration to the concrete tool callables an agent may use. Read
tools appear at READ; write tools are added only at READ_WRITE; a capability no
running integration provides resolves to no tools at all. These tests pin that
access gating without standing up real brokers.
"""

import pytest

from integrations.permissions import Access, Capability
from sdk.tools._integration_tools import integration_tools_for
from tools.integrations.types import RegisteredIntegration


def _integrations(*, cap: Capability, access: Access, state: str = "running") -> list[RegisteredIntegration]:
    """One running integration granting ``access`` for ``cap``."""
    return [
        RegisteredIntegration(
            id="acct-1",
            slug="acct",
            permissions={cap: access},
            state=state,
        )
    ]


def _names(tools) -> set[str]:
    return {t.__name__ for t in tools}


@pytest.mark.unit
def test_read_access_yields_read_tools_only() -> None:
    tools = integration_tools_for(Capability.EMAIL, _integrations(cap=Capability.EMAIL, access=Access.READ))
    names = _names(tools)
    assert "search_email" in names
    assert "list_email_messages" in names
    # Write tools stay out at READ.
    assert "send_email" not in names
    assert "move_email" not in names


@pytest.mark.unit
def test_read_write_access_adds_write_tools() -> None:
    names = _names(
        integration_tools_for(Capability.EMAIL, _integrations(cap=Capability.EMAIL, access=Access.READ_WRITE))
    )
    # Read tools are still present...
    assert "search_email" in names
    # ...and write tools are now included.
    assert "send_email" in names
    assert "move_email" in names


@pytest.mark.unit
def test_absent_capability_yields_no_tools() -> None:
    # Records grant a different capability — email is absent.
    records = _integrations(cap=Capability.CALENDAR, access=Access.READ_WRITE)
    assert integration_tools_for(Capability.EMAIL, records) == []


@pytest.mark.unit
def test_no_integrations_yields_no_tools() -> None:
    assert integration_tools_for(Capability.EMAIL, []) == []


@pytest.mark.unit
def test_non_running_integration_is_ignored() -> None:
    records = _integrations(cap=Capability.EMAIL, access=Access.READ_WRITE, state="auth_failed")
    assert integration_tools_for(Capability.EMAIL, records) == []


@pytest.mark.unit
def test_off_access_yields_no_tools() -> None:
    records = _integrations(cap=Capability.EMAIL, access=Access.OFF)
    assert integration_tools_for(Capability.EMAIL, records) == []


@pytest.mark.unit
def test_contacts_is_read_only() -> None:
    # Contacts has no write tier; READ_WRITE resolves to the same read tools.
    read = _names(integration_tools_for(Capability.CONTACTS, _integrations(cap=Capability.CONTACTS, access=Access.READ)))
    read_write = _names(
        integration_tools_for(Capability.CONTACTS, _integrations(cap=Capability.CONTACTS, access=Access.READ_WRITE))
    )
    assert "search_contacts" in read
    assert read == read_write


@pytest.mark.unit
def test_http_read_offers_call_api() -> None:
    names = _names(integration_tools_for(Capability.HTTP, _integrations(cap=Capability.HTTP, access=Access.READ)))
    assert "call_api" in names


@pytest.mark.unit
def test_returns_callables() -> None:
    tools = integration_tools_for(Capability.DRIVE, _integrations(cap=Capability.DRIVE, access=Access.READ_WRITE))
    assert tools
    assert all(callable(t) for t in tools)
