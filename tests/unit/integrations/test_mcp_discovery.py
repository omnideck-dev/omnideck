"""Bounds and immutability of data received from remote tool catalogs."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.tools import SchemaTool
from brokering.mcp_protocol import discover
from brokering.supervisor._operation_metadata import catalog_digest
from integrations.discovery import MAX_CATALOG_BYTES, parse_discovered_operations


def descriptor(**overrides):
    return {"id": "mcp.read", "title": "Read", "description": "", "input_schema": {"type": "object"}, **overrides}


@pytest.mark.parametrize("entries", [
    {}, [descriptor(), descriptor()], [descriptor(id="email.messages.send")],
    [descriptor(id="mcp.invalid/name")], [descriptor(title=3)], [descriptor(input_schema=[])],
    [descriptor(description="x" * 16385)],
])
def test_invalid_catalogs_are_rejected(entries):
    with pytest.raises(ValueError):
        parse_discovered_operations(json.dumps(entries))


def test_public_descriptors_cannot_mutate_cached_schema():
    operation, = parse_discovered_operations(json.dumps([descriptor()]))
    operation.public_dict()["input_schema"]["type"] = "string"
    assert operation.public_dict()["input_schema"] == {"type": "object"}


@pytest.mark.parametrize("schema,reason", [
    ({"type": "string"}, "invalid input schema"),
    ({"type": "object", "properties": {"count": {"type": "integerish"}}}, "invalid input schema"),
    ({"type": "object", "$schema": []}, "invalid input schema"),
    ({"type": "object", "$schema": "https://example.invalid/future"}, "unsupported schema version"),
])
async def test_discovery_retains_rejected_tools_without_disabling_valid_siblings(schema, reason):
    tools = [SimpleNamespace(name=name, title=name, description="", input_schema=value)
             for name, value in (("valid", {"type": "object"}), ("rejected", schema))]
    client = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools, next_cursor=None)))
    good, rejected = await discover(client)
    assert good.unavailable_reason is None
    assert reason in rejected.unavailable_reason
    assert rejected.public_dict()["input_schema"] == schema
    assert "unavailable_reason" not in rejected.public_dict()
    assert rejected.selection_dict()["unavailable_reason"] == rejected.unavailable_reason
    original = [good.public_dict(), rejected.public_dict()]
    # API-provided flags are never authoritative; reconstruct eligibility locally.
    wire = [{**entry, "unavailable_reason": None} for entry in original]
    restored = parse_discovered_operations(json.dumps(wire))
    assert restored[1].unavailable_reason == rejected.unavailable_reason
    assert catalog_digest(restored) == catalog_digest((good, rejected))
    if schema["type"] == "object":
        with pytest.raises(ValueError, match="schema"):
            SchemaTool("rejected", "", schema, AsyncMock())


def test_supported_older_schema_remains_selectable():
    schema = {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
              "properties": {"pair": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}}}
    operation, = parse_discovered_operations(json.dumps([descriptor(input_schema=schema)]))
    assert operation.unavailable_reason is None
    assert operation.public_dict()["input_schema"] == schema


async def test_discovery_bounds_total_bytes_before_fetching_more_pages():
    tool = SimpleNamespace(name="read", title=None, description="", input_schema={
        "type": "object", "description": "x" * MAX_CATALOG_BYTES,
    })
    client = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=[tool], next_cursor="next")))
    with pytest.raises(ValueError, match="too large"):
        await discover(client)
    assert client.list_tools.await_count == 1
