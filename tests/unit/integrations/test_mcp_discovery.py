"""Bounds and immutability of data received from remote tool catalogs."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from brokering.brokers.mcp_broker.client import discover
from integrations.discovery import MAX_CATALOG_BYTES, parse_discovered_operations


def descriptor(**overrides):
    return {"id": "mcp.read", "title": "Read", "description": "", "input_schema": {"type": "object"}, **overrides}


@pytest.mark.parametrize("entries", [
    {}, [descriptor(), descriptor()], [descriptor(id="email.messages.send")],
    [descriptor(id="mcp.invalid/name")], [descriptor(title=3)], [descriptor(input_schema={"type": "string"})],
    [descriptor(description="x" * 16385)],
])
def test_invalid_catalogs_are_rejected(entries):
    with pytest.raises(ValueError):
        parse_discovered_operations(json.dumps(entries))


def test_public_descriptors_cannot_mutate_cached_schema():
    operation, = parse_discovered_operations(json.dumps([descriptor()]))
    operation.public_dict()["input_schema"]["type"] = "string"
    assert operation.public_dict()["input_schema"] == {"type": "object"}


async def test_discovery_bounds_total_bytes_before_fetching_more_pages():
    tool = SimpleNamespace(name="read", title=None, description="", input_schema={
        "type": "object", "description": "x" * MAX_CATALOG_BYTES,
    })
    client = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=[tool], next_cursor="next")))
    with pytest.raises(ValueError, match="too large"):
        await discover(client)
    assert client.list_tools.await_count == 1
