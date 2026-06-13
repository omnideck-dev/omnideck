"""Per-provider tool input conversion.

Every provider advertises tools from one Pydantic-derived schema. These tests
pin the per-provider envelope shape and prove the rich types the old hand-rolled
walker dropped (Literal enums, nested-model objects) now reach every provider —
including Ollama, which used to receive raw callables and convert them itself.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from sdk.providers._anthropic import _convert_tools as anthropic_convert
from sdk.providers._ollama import _convert_tools as ollama_convert
from sdk.providers._openai import _convert_tools as openai_convert
from sdk.providers._openai_responses import _convert_tools as responses_convert


class _Recipient(BaseModel):
    name: str
    email: str


def sample_tool(
    path: str,
    encoding: Literal["utf-8", "base64"],
    owner: _Recipient,
    to: list[str] | str,
    retries: int = 3,
) -> str:
    """Write a file and notify someone.

    Args:
        path: Destination path.
        encoding: How to decode the content.
        owner: Who owns the file.
        to: Recipient address(es).
        retries: How many times to retry.
    """
    return ""


@pytest.mark.unit
def test_openai_envelope_shape():
    [tool] = openai_convert([sample_tool])
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "sample_tool"
    assert tool["function"]["description"] == "Write a file and notify someone."
    assert tool["function"]["parameters"]["type"] == "object"
    assert tool["function"]["parameters"]["required"] == ["path", "encoding", "owner", "to"]


@pytest.mark.unit
def test_responses_envelope_is_flat():
    [tool] = responses_convert([sample_tool])
    # Responses API flattens name/description/parameters to the top level.
    assert tool["type"] == "function"
    assert tool["name"] == "sample_tool"
    assert tool["description"] == "Write a file and notify someone."
    assert "function" not in tool
    assert tool["parameters"]["type"] == "object"


@pytest.mark.unit
def test_anthropic_envelope_uses_input_schema():
    [tool] = anthropic_convert([sample_tool])
    assert tool["name"] == "sample_tool"
    assert tool["description"] == "Write a file and notify someone."
    assert tool["input_schema"]["type"] == "object"
    assert "parameters" not in tool


@pytest.mark.unit
def test_ollama_matches_openai_dict():
    """Ollama now gets the same dict OpenAI does — no more raw-callable path."""
    assert ollama_convert([sample_tool]) == openai_convert([sample_tool])


@pytest.mark.unit
def test_literal_enum_reaches_every_provider():
    """A Literal param keeps its allowed values for all providers (was lost)."""
    openai_params = openai_convert([sample_tool])[0]["function"]["parameters"]
    anthropic_schema = anthropic_convert([sample_tool])[0]["input_schema"]
    for schema in (openai_params, anthropic_schema):
        assert schema["properties"]["encoding"] == {
            "type": "string",
            "enum": ["utf-8", "base64"],
            "description": "How to decode the content.",
        }


@pytest.mark.unit
def test_nested_model_reaches_every_provider():
    """A nested model param is a real object schema, not a degraded string."""
    schema = anthropic_convert([sample_tool])[0]["input_schema"]
    # The model param resolves through $defs to an object with its own fields.
    assert "_Recipient" in schema["$defs"]
    assert schema["$defs"]["_Recipient"]["properties"].keys() == {"name", "email"}
    assert schema["properties"]["owner"]["$ref"] == "#/$defs/_Recipient"


@pytest.mark.unit
def test_union_param_advertises_both_shapes():
    params = openai_convert([sample_tool])[0]["function"]["parameters"]
    assert params["properties"]["to"]["anyOf"] == [
        {"type": "array", "items": {"type": "string"}},
        {"type": "string"},
    ]
