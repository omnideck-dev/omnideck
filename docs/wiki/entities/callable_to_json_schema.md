---
title: callable_to_json_schema
type: entity
tags: [tools, schema, docstring, json-schema, llm]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]", "[[Source - SDK Overview]]"]
---

# callable_to_json_schema

## Overview

`callable_to_json_schema(func)` (in `sdk/tools/_callable_schema.py`) converts a Python callable into an OpenAI-style tool JSON schema. It uses Python's `inspect.signature()` and Google-style docstrings to generate parameter descriptions. This is how LLM-callable tools get their schema definitions.

## Details

**Output format:**
```json
{
  "type": "function",
  "function": {
    "name": "func_name",
    "description": "...",
    "parameters": {
      "type": "object",
      "properties": {"param": {"type": "string", "description": "..."}},
      "required": ["required_param"]
    }
  }
}
```

**Type mapping:**
- `str` → `"string"`, `int` → `"integer"`, `float` → `"number"`, `bool` → `"boolean"`
- `list[T]` → `{"type": "array", "items": ...}`
- `dict` → `{"type": "object"}`
- `Optional[T]` → unwraps to T (optionality carried by `required`)
- `T | S` (multi-type union) → `{"anyOf": [...]}`
- Uses `inspect.signature(func, eval_str=True)` to resolve `from __future__ import annotations` string annotations

**Description extraction:** reads the Google-style docstring body before the first section header (Args, Returns, etc.)

**Parameter description extraction:** parses the `Args:` section; handles continuation lines; maps param name → description

**Required params:** parameters with no default value are added to `required` list

**Tool token estimation:** `estimate_tool_tokens(func)` — serializes the schema and divides by 4 (chars per token)

**Usage by providers:**
- `AnthropicProvider._convert_tools()` — wraps in Anthropic format (`input_schema`)
- `OpenAIProvider` — passes directly as OpenAI tool definition

## Related Entities

- [[AnthropicProvider]] (converts tools using this)
- [[OpenAIProvider]] (converts tools using this)
- [[Tool Schema Generation and Dispatch]] concept
- [[BrowserTool]] (provides tools using Google-style docstrings)
- [[VirtualComputerTool]] (same)

## Sources

- [[Source - Tools Overview]]
- [[Source - SDK Overview]]
