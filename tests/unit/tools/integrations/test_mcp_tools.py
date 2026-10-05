import json
from dataclasses import replace
from unittest.mock import AsyncMock

from integrations.connection_cache import IntegrationConnection
from integrations.discovery import parse_discovered_operations
from tools.integrations._tool_resolution import integration_tools_by_category
from tools.integrations._mcp_tools import integration_service


async def test_connection_bound_tools_keep_schema_and_respect_grants(monkeypatch):
    schema = {"type": "object", "properties": {"integration_id": {"type": "string"}}}
    operations = parse_discovered_operations(json.dumps([
        {"id": "mcp.search", "title": "Search", "description": "Find messages", "input_schema": schema},
    ]))
    one = IntegrationConnection("one", "mcp", label="Work", discovered_operations=operations)
    assert not integration_tools_by_category((one,))["mcp"].tools
    one = replace(one, operation_grants=frozenset({"mcp.search"}))
    two = replace(one, id="two", label="Personal")
    tools = integration_tools_by_category((one, two))["mcp"].tools
    assert len(tools) == 2 and tools[0].__name__ != tools[1].__name__
    assert all(len(tool.__name__) <= 64 for tool in tools)
    assert tools[0].definition()["function"]["parameters"] == schema
    call = AsyncMock(return_value={"content": []})
    monkeypatch.setattr(integration_service, "invoke", call)
    await tools[1](integration_id="upstream-not-routing")
    call.assert_awaited_once_with("two", "mcp.search", {"integration_id": "upstream-not-routing"})
    assert not integration_tools_by_category((replace(one, state="broken"),))["mcp"].tools
