# Provider Structured Output — Technical Spec (Skeleton)

> **Status:** Skeleton / outline only. Full design **not** written yet — each
> section is a placeholder with a `TODO(design)` marker.
>
> **Scope:** the work to extend the provider/agent layer so an agent call can be
> constrained to return output conforming to a caller-supplied schema. Enabling
> work for the Workflows "structured results from agent steps" requirement; it is
> a standalone change and does not cover the Workflows feature itself. See
> `workflows-requirements.md` § "Structured results".

## 0. Goal, UX principle & approach

- **Goal:** a caller (an agent step) declares the output shape it wants; the
  engine returns data conforming to that shape, or fails cleanly after N attempts.
- **UX principle — the user sees none of this.** The user describes the desired
  output format in the editor (with help from the in-line assistant) and nothing
  else. No providers, no capabilities, no "this model supports schemas" toggles,
  no dialect caveats. It either works at dry-run time or it doesn't.
- **Approach — opportunistic native + universal parse/validate/retry:**
  - Set the provider's native structured-output field when it has one (harmless
    optimization; if the endpoint ignores it, the loop below still catches it).
  - Always validate the result against the schema. On mismatch, retry up to **N**
    times feeding the validation error back into the instruction. After N, fail
    the step cleanly.
- **Incapable models are caught at dry-run**, not by pre-flight gating. A model
  that can't reliably produce the shape fails validation, exhausts retries, and
  surfaces as a clear dry-run failure the user can act on (pick another model).
- **Non-goals:** cross-provider schema-dialect normalization (we own validation,
  so it's moot — see §5); the visual shape builder and agent-step wiring (those
  live in the Workflows design).

`TODO(design)`: exact success/failure contract; default and configurability of N.

## 1. The `chat()` contract change

How the schema enters the provider/agent call and what comes back.

- Optional schema param threaded into the call path (`Provider.chat()` in
  `sdk/providers/_protocol.py`, and/or the agent-run entrypoint that wraps it).
- Return-shape impact: validated data vs raw text vs the validation outcome on
  `ChatResponse` (or a wrapper above it).
- Omitting the param must behave exactly as today.

`TODO(design)`: where the retry loop lives (above the provider, in the agent
run path) vs what the provider itself exposes; signature; canonical schema
representation (pydantic model? JSON Schema dict?).

## 2. Opportunistic native pass

Best-effort use of each provider's native field — purely a cost/latency
optimization, never load-bearing for correctness.

| Provider | File | Native mechanism (set when present) |
|---|---|---|
| Ollama | `_ollama.py` | `format` (JSON schema) |
| OpenAI (chat) | `_openai.py` | `response_format: json_schema` |
| OpenAI (responses) | `_openai_responses.py` | `text.format` json_schema |
| Anthropic | `_anthropic.py` | `output_config: {format: {...}}` |
| Fake | `_fake.py` | test-only: emit schema-shaped fixture |

Endpoints that silently ignore the field (some OpenAI-compatible / OpenRouter
backends) are fine — they just fall through to the validate/retry path. **No
`supported_parameters` introspection or capability table is required.**

`TODO(design)`: per-provider request construction + response extraction; whether
to skip the native field for unknown OpenAI-compat endpoints or always attempt it.

## 3. Universal parse / validate / retry loop

The single correctness mechanism, provider-agnostic.

- Extract the candidate payload from the response.
- Validate against the schema (single lib — pydantic or jsonschema).
- On success → return typed data.
- On mismatch → retry, injecting the desired shape + the specific validation
  error into the next instruction, up to **N** attempts.
- After N failures → fail the step with a clear, typed error (surfaced in run
  history; in dry-run this is what tells the user the model can't do it).
- Distinguish genuine model refusal / max-tokens truncation from schema mismatch.

`TODO(design)`: N default + where it's configured; prompt construction for the
retry nudge; payload extraction (handling prose-wrapped JSON); validation lib;
interaction with existing hooks (`sdk/hooks/`).

## 4. Schema representation & v1 sub-language

Because **we** own validation (not the provider), we are the source of truth and
not bound to any provider's dialect.

- v1 accepted constructs: object/array, scalar types, `enum`, `required`.
- Can be expanded later (lengths, ranges, regex) since our validator enforces
  them regardless of provider — kept minimal in v1 to limit surface area.

`TODO(design)`: canonical internal schema form; how the editor/assistant author
it; how it maps to both the native field (§2) and our validator (§3).

## 5. Testing

- `FakeProvider` path for deterministic schema-shaped output.
- Native-pass unit tests per real provider adapter (field built correctly).
- Validate/retry tests: malformed JSON → retry → eventual success; and
  never-conforms → fail after N.
- Dry-run-style test proving an incapable model surfaces as a clean failure.

`TODO(design)`: test layout under `tests/`; fixtures; unit vs integration split.

## 6. Open questions

`TODO(design)`: canonical schema representation; N default; payload extraction
robustness; whether streaming + structured output is ever needed by a consumer;
where exactly the loop sits relative to the agent turn loop.

---

## Resolved decisions (carried from discussion)

- **User is fully insulated.** They specify a desired output shape in the editor
  (assisted by the in-line assistant); no provider/capability/dialect concepts
  ever surface to them. (§0)
- **Opportunistic native + universal parse/validate/retry, N times, then fail.**
  This *reverses* the earlier "native-only, no fallback" stance — the retry loop
  is back, but hidden from the user, and it's the universal correctness
  guarantee. (§0, §2, §3)
- **No user-facing capability gating and no `supported_parameters`
  introspection.** Incapable models are caught at **dry-run**, not pre-flight.
  This drops the OpenRouter/OpenAI-compat capability machinery entirely. (§0, §2)
- **We own validation**, so cross-provider dialect normalization is moot; the
  native field is a best-effort optimization only. (§2, §4)
- **All real providers have a native mechanism** to use opportunistically —
  Ollama `format`, OpenAI `response_format` / Responses `text.format`, Anthropic
  `output_config.format`. (§2)
