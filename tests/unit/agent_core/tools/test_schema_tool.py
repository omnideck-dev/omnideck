"""Dynamic schemas and executable callables share the normal tool boundary."""

from unittest.mock import AsyncMock

import pytest

from agent_core.tools import SchemaTool, callable_to_json_schema, _execute_tool_call, _prepare_tool_arguments


async def test_schema_and_arguments_are_lossless_and_isolated():
    schema = {
        "type": "object", "$defs": {"key": {"type": "string"}},
        "properties": {"key": {"$ref": "#/$defs/key"}, "value": {"anyOf": [{"type": "null"}, {"type": "object"}]}},
        "required": ["key"], "additionalProperties": False,
    }
    invoke = AsyncMock(return_value={"ok": True})
    tool = SchemaTool("remote_tool", "Use the remote service.", schema, invoke)
    definition = callable_to_json_schema(tool)
    assert definition["function"]["parameters"] == schema
    schema["required"].clear()
    schema["properties"].clear()
    definition["function"]["parameters"]["properties"].clear()
    assert "key" in callable_to_json_schema(tool)["function"]["parameters"]["properties"]
    with pytest.raises(ValueError, match="required"):
        await tool(value=None)
    invoke.assert_not_awaited()
    args = {"key": "01", "value": None}
    assert _prepare_tool_arguments(tool, args) == args
    result = await _execute_tool_call("remote_tool", args, [tool])
    assert result == "{'ok': True}"
    invoke.assert_awaited_once_with(args)


@pytest.mark.parametrize("through_executor", [False, True], ids=["direct", "agent"])
@pytest.mark.parametrize("arguments,path", [
    ({}, "$"),
    ({"items": [{"quantity": "2", "mode": "read"}]}, "$.items[0].quantity"),
    ({"items": [{"quantity": True, "mode": "read"}]}, "$.items[0].quantity"),
    ({"items": [{"quantity": 0, "mode": "read"}]}, "$.items[0].quantity"),
    ({"items": [{"quantity": 2, "mode": "delete"}]}, "$.items[0].mode"),
    ({"items": [{"quantity": 2, "mode": "read", "extra": 1}]}, "$.items[0]"),
    ({"items": [], "integration_id": "another-account"}, "$"),
])
async def test_invalid_arguments_never_reach_callback(arguments, path, through_executor):
    invoke = AsyncMock()
    tool = SchemaTool("ordered_items", "Use selected items.", {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/item"}}},
        "required": ["items"], "additionalProperties": False,
        "$defs": {"item": {
            "type": "object", "properties": {
                "quantity": {"type": "integer", "minimum": 1},
                "mode": {"enum": ["read", "write"]},
            }, "required": ["quantity", "mode"], "additionalProperties": False,
        }},
    }, invoke)
    if through_executor:
        error = await _execute_tool_call("ordered_items", arguments, [tool])
        assert error.startswith("Argument validation failed:")
    else:
        with pytest.raises(ValueError) as caught:
            await tool(**arguments)
        error = str(caught.value)
    assert f"at {path}:" in error
    invoke.assert_not_awaited()


async def test_validation_preserves_values_and_does_not_insert_defaults():
    invoke = AsyncMock()
    tool = SchemaTool("tree", "Use a tree.", {
        "type": "object", "properties": {
            "node": {"$ref": "#/$defs/node"},
            "limit": {"type": "integer", "default": 20},
        }, "required": ["node"],
        "$defs": {"node": {"type": "object", "properties": {
            "value": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
        }}},
    }, invoke)
    arguments = {"node": {"value": "01", "children": [{"value": None}]}}
    await tool(**arguments)
    invoke.assert_awaited_once_with(arguments)
    assert invoke.await_args.args[0]["node"] is arguments["node"]
    assert "limit" not in invoke.await_args.args[0]


async def test_additional_properties_follow_the_supplied_contract():
    invoke = AsyncMock()
    open_tool = SchemaTool("open", "Open inputs.", {"type": "object"}, invoke)
    await open_tool(extra="preserved")
    invoke.assert_awaited_once_with({"extra": "preserved"})
    invoke.reset_mock()
    typed_tool = SchemaTool("typed", "Typed inputs.", {
        "type": "object", "additionalProperties": {"type": "integer"},
    }, invoke)
    with pytest.raises(ValueError, match="integer"):
        await typed_tool(extra="2")
    invoke.assert_not_awaited()
    await typed_tool(extra=2)
    invoke.assert_awaited_once_with({"extra": 2})


@pytest.mark.parametrize("schema", [
    {"type": "not-a-type"},
    {"type": "object", "required": "query"},
    {"$schema": []},
    {"$schema": "https://example.invalid/unknown-dialect", "type": "object"},
])
def test_invalid_or_unknown_schema_is_rejected_at_construction(schema):
    with pytest.raises(ValueError, match="schema"):
        SchemaTool("invalid", "Invalid schema.", schema, AsyncMock())


async def test_declared_draft_is_used():
    invoke = AsyncMock()
    # Tuple-form items is valid Draft 7 but invalid under the default 2020-12.
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object", "properties": {
            "pair": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}],
                     "additionalItems": False},
        },
    }
    tool = SchemaTool("pair", "Use a pair.", schema, invoke)
    await tool(pair=["key", 2])
    invoke.assert_awaited_once_with({"pair": ["key", 2]})
    invoke.reset_mock()
    with pytest.raises(ValueError, match="integer"):
        await tool(pair=["key", "2"])
    invoke.assert_not_awaited()


@pytest.mark.parametrize("reference", ["https://example.invalid/schema", "file:///etc/passwd", "#/$defs/missing"])
@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
async def test_unresolvable_references_fail_without_retrieval(reference, keyword, monkeypatch):
    from unittest.mock import Mock
    import socket
    import urllib.request

    network = Mock(side_effect=AssertionError("No network allowed"))
    retrieve = Mock(side_effect=AssertionError("No external retrieval allowed"))
    monkeypatch.setattr(socket, "getaddrinfo", network)
    monkeypatch.setattr(urllib.request, "urlopen", retrieve)
    invoke = AsyncMock()
    tool = SchemaTool("reference", "Use referenced input.", {
        "type": "object", "properties": {"value": {keyword: reference}},
    }, invoke)
    with pytest.raises(ValueError, match="within the supplied schema"):
        await tool(value="anything")
    invoke.assert_not_awaited()
    network.assert_not_called()
    retrieve.assert_not_called()


async def test_embedded_resource_resolves_without_external_retrieval():
    invoke = AsyncMock()
    tool = SchemaTool("embedded", "Use embedded input.", {
        "$id": "https://example.invalid/root", "type": "object",
        "$defs": {"count": {"$id": "count", "type": "integer"}},
        "properties": {"value": {"$ref": "https://example.invalid/count"}},
    }, invoke)
    await tool(value=2)
    invoke.assert_awaited_once_with({"value": 2})
    invoke.reset_mock()
    with pytest.raises(ValueError, match="integer"):
        await tool(value="2")
    invoke.assert_not_awaited()
