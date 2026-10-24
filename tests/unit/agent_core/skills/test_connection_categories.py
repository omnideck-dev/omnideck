"""Selection identity, approval boundaries, and direct/skill union."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from agents import AgentProfile
from agent_runtime._factory import AgentFactory
from integrations.connection_cache import IntegrationConnection
from integrations.discovery import parse_discovered_operations
from skills._store import SkillRecord, save_skill_record
from skills._tool_categories import tool_categories
from tools.integrations._tool_resolution import connection_tools


def connection(id="work", **kwargs):
    return IntegrationConnection(id=id, slug="google", label="Work Google",
        operation_grants=frozenset({"email.messages.search"}), **kwargs)


@pytest.mark.unit
async def test_native_tools_are_bound_and_have_distinct_stable_names(monkeypatch):
    invoke = AsyncMock(return_value={"headers": []})
    monkeypatch.setattr("integrations.service.integration_service.invoke", invoke)
    a, b = connection_tools(connection()), connection_tools(connection("personal"))
    assert a[0].__name__ != b[0].__name__
    assert a[0].__name__ == connection_tools(replace(connection(), label="Renamed"))[0].__name__
    assert "integration_id" not in a[0].definition()["function"]["parameters"]["properties"]
    await a[0](query="hello")
    assert invoke.call_args.args[:2] == ("work", "email.messages.search")
    with pytest.raises(ValueError, match="overridden"):
        await a[0](query="hello", integration_id="personal")
    assert invoke.await_count == 1


@pytest.mark.unit
async def test_only_approved_operations_and_exact_connection_are_selected(tmp_path, monkeypatch):
    monkeypatch.setattr("skills._store._skills_dir", lambda: tmp_path)
    save_skill_record(SkillRecord(id="mail", name="Mail", tool_categories=["integration:work"]))
    profile = AgentProfile(id="a", name="A", skills=["mail"], tool_categories=["integration:work"])
    snapshot = (connection(), connection("personal"))
    factory = AgentFactory()
    state = await factory.build_capabilities(profile, spawn_agent=AsyncMock(), connections=snapshot)
    name = connection_tools(snapshot[0])[0].__name__
    assert [t.__name__ for t in state.tools].count(name) == 1
    assert connection_tools(snapshot[1])[0].__name__ not in {t.__name__ for t in state.tools}
    # Removing the direct grant leaves the skill contribution; removing both removes access.
    state = await factory.build_capabilities(profile.model_copy(update={"tool_categories": []}), spawn_agent=AsyncMock(), connections=snapshot)
    assert name in {t.__name__ for t in state.tools}
    state = await factory.build_capabilities(profile.model_copy(update={"skills": [], "tool_categories": []}), spawn_agent=AsyncMock(), connections=snapshot)
    assert name not in {t.__name__ for t in state.tools}
    for next_snapshot in ((), (replace(snapshot[0], operation_grants=frozenset()),), (replace(snapshot[0], state="stopped"),), (connection("new-id"),)):
        state = await factory.build_capabilities(profile, spawn_agent=AsyncMock(), connections=next_snapshot)
        assert name not in {t.__name__ for t in state.tools}


@pytest.mark.unit
async def test_mcp_and_native_connections_share_catalog_identity():
    operations = parse_discovered_operations('[{"id":"mcp.lookup","title":"Look up","description":"Find a record","input_schema":{"type":"object","properties":{}}}]')
    remote = replace(connection("mcp-one"), slug="mcp", discovered_operations=operations, operation_grants=frozenset({"mcp.lookup"}))
    cats = await tool_categories((connection(), remote))
    assert cats["integration:work"].connection_id == "work"
    assert cats["integration:mcp-one"].connection_id == "mcp-one"
    assert "email" not in cats and "mcp" not in cats
    assert len(cats["integration:mcp-one"].tools) == 1
