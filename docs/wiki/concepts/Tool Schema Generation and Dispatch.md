---
title: Tool Schema Generation and Dispatch
type: concept
tags: [tools, schema, json-schema, dispatch, docstring]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - SDK Overview]]", "[[Source - Tools Overview]]"]
---

# Tool Schema Generation and Dispatch

## Overview

Tool Schema Generation is the process of converting Python callables into JSON Schema definitions that LLMs can use to invoke them. Tool Dispatch is the reverse: taking an LLM's tool call (name + JSON arguments) and routing it to the correct Python function. Together these form the complete tool system.

## How It Works

**Schema Generation (`callable_to_json_schema`):**
1. `inspect.signature(func, eval_str=True)` — get parameter names, types, defaults
2. `inspect.getdoc(func)` — get the function's docstring
3. Parse Google-style `Args:` section to extract per-parameter descriptions
4. Map Python types to JSON Schema types (str→string, int→integer, Optional[T]→T, list[T]→array, etc.)
5. Parameters with no default → added to `required` list
6. Return OpenAI-style `{type: "function", function: {name, description, parameters}}`

**Provider-specific conversion:**
- OpenAI/OpenRouter: use schema as-is
- Anthropic: rename `parameters` → `input_schema`; wrap in `{name, description, input_schema}`
- Ollama: accepts raw callables directly (no JSON schema needed)

**Dispatch (`_execute_tool_call(tool_name, tool_arguments, tools)`):**
1. Find the tool function by `__name__` in the tools list
2. If not found: return error message string
3. Parse `tool_arguments` (JSON string or dict)
4. Call `_prepare_tool_arguments(func, args_dict)` — coerce types, validate
5. Call `await func(**prepared_args)` (async) or `func(**prepared_args)` (sync)
6. `_normalize_tool_result(result)` — convert to string for history storage

**Tool result normalization:**
- `None` → `"No result"`
- Pydantic models → JSON
- dicts/lists → JSON
- Strings → as-is
- `ToolResultCapHook` truncates excessively long results

**Google-style docstrings are the LLM's documentation:**
- Function description (before first section header) → LLM learns when to use the tool
- `Args:` section descriptions → LLM knows what each parameter means
- CRITICAL: these docstrings are for the model, not the developer; implementation details should be absent

## Key Details

- `eval_str=True` in `inspect.signature` resolves `from __future__ import annotations` string annotations — without this, every parameter would collapse to the default schema type
- Tool functions can be sync or async; `_execute_tool_call` handles both
- The `before_tool` hook can intercept a tool call entirely (return non-None to replace execution)
- `estimate_tool_tokens(func)` approximates the context cost of including a tool schema (~chars/4)

## Sources

- [[Source - SDK Overview]]
- [[Source - Tools Overview]]
