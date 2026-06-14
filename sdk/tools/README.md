# sdk/tools

Plumbing that sits between an LLM's tool calls and the plain Python functions
that implement them. A "tool" here is just a callable — its signature is the
runtime validation schema and its Google-style docstring is the model-facing
documentation. There is no decorator and no registration step; a tool is any
function handed to the turn loop.

## One model, both directions

Each tool's signature is turned into a single Pydantic model (`_tool_model.py`),
and that one model drives everything:

1. **Inbound** — `model.model_validate(args)` coerces a tool-call's JSON
   arguments into typed Python values, then the call runs and the result is
   normalized back to a string. (`_helpers.py` delegates here.)
2. **Outbound** — `model.model_json_schema()` produces the JSON Schema that
   providers advertise to the model. (`_callable_schema.py` wraps it in the
   OpenAI tool envelope.)

Because both the schema the model sees and the validation applied to its reply
come from the *same* model, they cannot drift. This replaced two hand-rolled
annotation walkers (one per direction) plus a third hidden converter inside the
Ollama client.

## Public surface

Re-exported from `sdk.tools` (`__init__.py` is a pure facade):

| Name | Source | What it does |
| --- | --- | --- |
| `_execute_tool_call` | `_helpers` | Resolve a tool by name, validate args, run it, return a string for the model. The inbound entry point. |
| `_prepare_tool_arguments` | `_helpers` | Validate/coerce a raw arg dict against a callable's signature (delegates to `_tool_model`). |
| `_normalize_tool_result` | `_helpers` | Recursively flatten a tool's return value (Pydantic models, dicts, sequences) into JSON-serializable data. |
| `_summarize_arguments` | `_helpers` | Stringify + length-cap args for UI display events. |
| `callable_to_json_schema` | `_callable_schema` | Build an OpenAI-style tool schema from a callable. The outbound entry point. |
| `estimate_tool_tokens` | `_callable_schema` | Rough token cost of including a tool's schema in a request. |

Internal modules behind those:

- `_tool_model.py` — builds and caches the per-tool Pydantic model; exposes
  `tool_model`, `parameters_schema` (outbound), and `validate_arguments`
  (inbound). The single source of truth for tool typing.
- `_docstrings.py` — a dependency-free leaf that parses Google-style docstrings
  for the tool description and per-parameter descriptions. Both directions read
  it, so it lives one layer down to avoid a cycle.

The leading underscores on the `_helpers` exports are historical; they are
imported across the package and treated as public-within-`sdk`.

`_spawn_agent.py` lives in this package but is not part of the surface above —
`spawn_agent` is itself a *tool* (an LLM-callable function that runs a
sub-agent in an isolated context). It is consumed by the agent/skill layer that
assembles tool sets, not imported as a utility.

## Inbound path (how a tool call becomes a Python call)

```
provider emits {name, arguments}                  # arguments already a dict
        │
        ▼
_execute_tool_call(name, arguments, tools)        # _helpers.py
        │  · strips "fn(kw=...)" call syntax some models emit
        │  · publishes a tool_call UI event (args summarized)
        │  · matches the callable by __name__
        ▼
validate_arguments(func, arguments)               # _tool_model.py
        │  · tool_model(func).model_validate(arguments)
        │  · ValidationError → ValueError naming the bad parameter
        ▼
await func(**typed_kwargs)  →  _normalize_tool_result  →  str for the model
```

### Coercion is strict; tools are forgiving

Validation runs against the annotation and **raises** on a mismatch — e.g. a
bare string where `list[str]` is annotated is rejected with a named error so the
model gets a corrective message instead of silently iterating the string
character by character. Pydantic also rejects the lossy cases the old coercer
let through (a non-integer float for an `int`, an out-of-set value for a
`Literal`). Annotations are the contract.

When a tool genuinely wants to accept more than one shape, it widens its own
signature (`to: list[str] | str`) and normalizes internally. Leniency lives in
the tool, not in the generic validation layer. The one carried-over convenience:
a model/list-of-model parameter sent as a JSON *string* is decoded before
validation, since models sometimes double-encode nested objects.

## Outbound path (how a callable becomes a schema)

`parameters_schema(func)` builds the model, emits `model_json_schema()`, and
post-processes it to the shape providers expect:

- Signature is read with `eval_str=True`, so tools declared under
  `from __future__ import annotations` (most of them) get **real types**, not
  the stringized `"list[str]"` PEP 563 stores.
- `title` and `default` keys are dropped (lean, stable schema).
- `None` is removed from unions — optionality rides on `required`, not the
  type — so `Optional[T]` collapses to `T`. A genuinely multi-typed param like
  `list[str] | str` stays an `anyOf` of all accepted shapes.
- `additionalProperties: true` (the JSON-Schema default) is dropped, so a bare
  `dict` reads as a plain object; a typed `dict[str, str]` keeps its value
  schema.

`callable_to_json_schema` wraps that parameter schema plus the docstring
description in the OpenAI tool envelope. **Every** provider advertises tools from
this one schema: `_openai.py` uses it as-is, `_openai_responses.py` flattens it,
`_anthropic.py` remaps it to `input_schema`, and `_ollama.py` sends the same
OpenAI-style dict (it used to receive raw callables and convert them in the
client library — that path is gone).

`anyOf` is valid in every provider's tool schema, but adherence varies across
the weaker models behind OpenRouter — keep widened unions to where a tool truly
accepts more than one shape rather than as a habit.

## Design notes for future readers

- **Annotations are the source of truth.** One Pydantic model per tool produces
  both the schema and the validation, so keep tool signatures precise; the
  docstring carries the human/LLM intent, the types carry the machine contract.
- **Don't reintroduce a parallel walker.** The whole point of this layer is that
  Pydantic does the single annotation walk. If a new type shape needs handling,
  fix it in the one model build (or its post-processing), not in a second
  hand-rolled path.
