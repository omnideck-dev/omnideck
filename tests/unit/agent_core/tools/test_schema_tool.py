"""Dynamic schemas and executable callables share the normal tool boundary."""

from unittest.mock import AsyncMock

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
    definition["function"]["parameters"]["properties"].clear()
    assert callable_to_json_schema(tool)["function"]["parameters"] == schema
    args = {"key": "01", "value": None}
    assert _prepare_tool_arguments(tool, args) == args
    result = await _execute_tool_call("remote_tool", args, [tool])
    assert result == "{'ok': True}"
    invoke.assert_awaited_once_with(args)
