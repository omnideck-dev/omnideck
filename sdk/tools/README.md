# sdk/tools

Plumbing that sits between an LLM's tool calls and the plain Python functions
that implement them. A "tool" here is just a callable — its signature is the
runtime validation schema and its Google-style docstring is the model-facing
documentation. There is no decorator and no registration step; a tool is any
function handed to the turn loop.

The package does two jobs:

1. **Inbound** — turn a tool-call (name + JSON args) into a real Python call:
   match the function, coerce the arguments to the annotated types, run it,
   normalize the result back to a string. (`_helpers.py`)
2. **Outbound** — turn a callable into the JSON Schema some providers require
   in order to advertise the tool to the model. (`_callable_schema.py`)

## Public surface

Re-exported from `sdk.tools` (`__init__.py` is a pure facade):

| Name | Source | What it does |
| --- | --- | --- |
| `_execute_tool_call` | `_helpers` | Resolve a tool by name, validate args, run it, return a string for the model. The inbound entry point. |
| `_prepare_tool_arguments` | `_helpers` | Validate/coerce a raw arg dict against a callable's signature. |
| `_normalize_tool_result` | `_helpers` | Recursively flatten a tool's return value (Pydantic models, dicts, sequences) into JSON-serializable data. |
| `_summarize_arguments` | `_helpers` | Stringify + length-cap args for UI display events. |
| `callable_to_json_schema` | `_callable_schema` | Build an OpenAI-style tool schema from a callable's signature + docstring. The outbound entry point. |
| `estimate_tool_tokens` | `_callable_schema` | Rough token cost of including a tool's schema in a request. |

The leading underscores on the `_helpers` exports are historical; they are
imported across the package and treated as public-within-`sdk`.

`_spawn_agent.py` lives in this package but is not part of the surface above —
`spawn_agent` is itself a *tool* (an LLM-callable function that runs a
sub-agent in an isolated context). It is consumed by the agent/skill layer that
assembles tool sets, not imported as a utility.

## Inbound path (how a tool call becomes a Python call)

```
provider emits {name, arguments}
        │
        ▼
_execute_tool_call(name, arguments, tools)        # _helpers.py
        │  · strips "fn(kw=...)" call syntax some models emit
        │  · publishes a tool_call UI event (args summarized)
        │  · matches the callable by __name__
        ▼
_prepare_tool_arguments(func, arguments)
        │  · inspect.signature(func, eval_str=True)
        │  · per param: _coerce_value(annotation, value)
        │  · fills defaults, raises on missing required
        ▼
_coerce_value(expected_type, value)
        │  · unwraps Optional[T] / T | None
        │  · list[T]  → must be a list; coerces each item (raises otherwise)
        │  · Pydantic → json.loads if str, then model_validate
        │  · bool/int/float/str → scalar coercion
        ▼
await func(**validated)  →  _normalize_tool_result  →  str for the model
```

### Coercion is strict; tools are forgiving

`_coerce_value` validates against the annotation and **raises** on a mismatch —
e.g. a bare string where `list[str]` is annotated is rejected with a named
error so the model gets a corrective message instead of silently iterating the
string character by character. Annotations are the contract.

When a tool genuinely wants to accept more than one shape, it widens its own
signature (`to: list[str] | str`) and normalizes internally. Leniency lives in
the tool, not in the generic coercion layer.

## Outbound path (how a callable becomes a schema)

`callable_to_json_schema` reads the signature and the Google-style docstring:

- Signature is read with `eval_str=True`, so tools declared under
  `from __future__ import annotations` (most of them) get **real types**, not
  the stringized `"list[str]"` PEP 563 stores. Without this every such param
  collapses to the default schema type. The cost: a param's annotation must be
  importable from the tool's module globals at conversion time.
- Parameter types → JSON Schema via `_python_type_to_json_schema`.
- The docstring's leading paragraph → tool `description`.
- The docstring's `Args:` section → per-parameter `description`s.
- Params without a default → `required`.

Only the providers that require an explicit schema call this:
`sdk/providers/_openai.py`, `_openai_responses.py`, `_anthropic.py` (OpenRouter
rides the OpenAI path). **Ollama does not** — it accepts raw callables and runs
its own pydantic-based conversion inside the client library. The two conversion
paths are independent, which is why a signature change can affect one and not
the other.

Union handling: `None` is dropped (optionality is carried by `required`, not
the type). A single remaining member collapses to that member (`Optional[T]` →
`T`); a genuinely multi-typed param like `list[str] | str` becomes an `anyOf`
of all accepted shapes, so the model sees both the array and the scalar form.
`anyOf` is valid in OpenAI/Anthropic tool schemas, but adherence varies across
the weaker models behind OpenRouter — keep widened unions to where a tool truly
accepts more than one shape rather than as a habit.

## Design notes for future readers

- **Annotations are the source of truth.** Both the validator and the OpenAI
  schema generator read `inspect.signature`. Keep tool signatures precise; the
  docstring carries the human/LLM intent, the types carry the machine contract.
- **Two independent type→schema implementations exist** in this area:
  `_coerce_value` (inbound validation) and `_python_type_to_json_schema`
  (outbound OpenAI/Anthropic schema). They share no code and have drifted in
  edge cases (union handling differs between them). Consolidating or replacing
  them with a library is tracked as a future refactor.
