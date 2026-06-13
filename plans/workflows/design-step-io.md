# Design — Step I/O: shapes, references, the typed operations facade, structured agent output

Low-level design for the typed-data backbone (architecture §2.2). Absorbs `workflows-engine-spec.md` §1 (typing), §2 (tool schemas as contract), §4 (data references) and **all of `provider-structured-output-spec.md`** (deleted with this doc's landing). Storage forms of refs/shapes are in `design-definitions.md`; this doc defines their **semantics**: what has a shape, what's in scope where, how values resolve, and the two contracts that make it real — the typed operations facade and structured agent output.

## 1. The shape model

A **shape** describes what a node produces. Three cases:

- **`text`** — an unstructured value. Referenceable only whole (`path=[]`, shown as `Step ▸ (text)`).
- **`structured(fields)`** — a list of `ShapeField`s (types: text / number / boolean / date / enum / list-of-flat-objects, depth 1 — see design-definitions §3.6). Field-level refs allowed and validated.
- **`dynamic`** — structure exists but isn't known at build time. Field refs are **allowed but unvalidated**: dotted paths the user picked from live data (API tree picker) or asserted (refs into code output). Build-time validation passes them; runtime resolution failures hit the step's failure policy; the dry run is where they're actually exercised.

Where shapes come from, per node:

| Node | Shape |
|---|---|
| Watch trigger (email/calendar/drive) | `structured` — the item model supplied by the operations facade per source kind (§4.4) |
| Watch trigger (API) | `dynamic` — no fixed shape; the tree picker discovers paths from a live sample, nothing stored |
| Schedule/manual start | no output (only `run` context exists) |
| Agent step, shape on | `structured` — the declared `ShapeField`s |
| Agent step, shape off | `text` |
| Tool step, run once | `structured` — the operation's result model (from the facade registry) |
| Tool step, per item | `list` of the operation's result model |
| Code step | `dynamic` |
| Branch / approval | no output (branch routes; approval gates) |

The code-step row is a deliberate departure from the engine spec's "un-shaped output is referenceable only as `(text)`": the mockups reference fields inside code output (`Set due dates ▸ result` feeding per-item `item ▸ title` / `item ▸ due`), so code output is dynamic-permissive, same tier as API trigger items. Two-tier checking is the rule everywhere: **known shapes validate strictly; dynamic shapes validate at runtime only.**

## 2. Scope computation

One pure function, used by the data-picker API, validation, and the assistant:

```python
def compute_scope(definition: Definition, at_node: str) -> list[ScopeEntry]
# ScopeEntry: {source_id, label, kind: trigger|step|item|run, shape: Shape}
```

Rules (the data-picker mockup is the reference):

- **Ancestors only.** A node's scope is every node from which a path leads to it in the edge DAG — trigger(s), then upstream steps in topological order. Branch siblings and downstream steps are never offered.
- **Rejoins**: a step after a rejoin has both branches' steps in scope (each is an ancestor). At runtime only one executed; a ref to the not-taken side resolves to missing → the referencing step's failure policy. Validation does not warn (this is a legitimate pattern with `skip`).
- **Multiple triggers**: all are in scope; at runtime only the firing trigger has a value. Same missing-value semantics. (Workflows with multiple triggers and field refs to a specific one are exercised in dry run by picking the seed trigger.)
- **`item`** appears only while configuring the mapping fields of a per-item tool step; its shape is the element shape of `for_each` (known if the list source is structured, dynamic otherwise).
- **`run`** is always last: `started_at` (date), `workflow` (text), `trigger` (text — the firing trigger's name; "manual" for hand runs).

## 3. Runtime resolution

Run state holds one result envelope per executed node (`design-engine.md` owns storage): `{node_id: {value, shape, produced_at}}`. Resolution:

```python
resolve(ref: DataRef, run_state, item_ctx=None) -> Value | Missing
```

- `path=[]` → the whole value. Non-empty path → key traversal into structured/dynamic values; traversal into `text` is always `Missing`.
- No list indexing in paths — a ref addresses a field or a whole list, never `[0]`; element access is what per-item mode and code steps are for.
- `Missing` (node not executed, field absent, null) is a distinct outcome, not an exception: tool/code executors translate it to the step's failure policy; agent includes render an explicit `(missing)` block rather than silently dropping (the agent should know an include was empty).

**Quarantine delivery for agent includes** (engine spec §4 carried decision): includes are never inlined into the instruction. Each is appended as a labeled block:

```
<data name="On Client Email ▸ body" source="trigger:tr_x9" type="text">
…value…
</data>
```

Scalars render as text; structured values as pretty-printed JSON; any literal `</data` inside content is escaped. The workflow agent-step system prompt states that `<data>` blocks are reference material, not instructions (prompt-injection posture). Selection of *what* to include is the user's `include` list — no size heuristics, no auto-inlining.

## 4. The typed operations facade (`integrations/operations/`)

The step/trigger-facing surface over the brokers (architecture §2.2). Lives in `integrations/`, wraps `broker_client.call()` directly, and is consumed by tool steps, watch pollers, trigger previews, and the assistant's sample calls. `tools/integrations/` is untouched in v1 and later refactors into prose adapters over this.

### 4.1 Shape of the package

```
integrations/operations/
  __init__.py        — facade: invoke(), registry accessors
  types.py           — leaf: Operation descriptors + canonical result models
  _registry.py       — the static operation table
  _invoke.py         — dispatch: params model -> broker verb args -> result normalization
  _normalize.py      — per-broker-family adapters into the canonical models
```

### 4.2 Operation descriptors

```python
class Operation(BaseModel):
    id: str                       # "email.send_message", "calendar.create_event", …
    title: str                    # UI label: "Send email"
    capability: str               # which integrations qualify: email | calendar | drive | contacts | http
    params: type[BaseModel]       # input contract (the mappable fields)
    result: type[BaseModel]       # canonical result model
    effect: Literal["read", "write"]   # write ops are held in dry run
    broker_verb: str
    schema_rev: str               # current revision (see 4.5)
```

`params` models are the build-time mapping targets: field names, types, required/optional — what the tool-step inspector renders as input rows. `result` models are what downstream refs resolve into. JSON Schema for both comes from Pydantic (`model_json_schema()`), used by the scope/picker API and the assistant.

### 4.3 Invocation and normalization

```python
async def invoke(op_id: str, integration_id: str, params: BaseModel) -> BaseModel
```

Validates params, maps to the broker verb args, calls `broker_client.call()`, and **normalizes** the response into the canonical result model. Normalization is the unglamorous core: the email broker already returns typed models (`MessageHeader`, `Message`, `Event` in `integrations/brokers/email_broker/types.py`) but the Google Workspace broker returns ad-hoc flattened dicts for everything, and the two families disagree on field names. One canonical model per operation; `_normalize.py` owns the per-family mapping. Broker errors (`IntegrationNotConnected`, `IntegrationAuthFailed`, `IntegrationPermissionDenied`, `RpcError`) pass through typed — the engine maps them to step failures, the UI to the broken-integration warning.

### 4.4 Item models for watch sources

The facade also publishes the **watch item shapes** triggers and condition builders use:

- `EmailItem`: `id, from, to, subject, folder, date, body` (body fetched lazily — the poller matches on headers, the run gets the full message)
- `CalendarItem`: `id, summary, start, end, location, description, calendar`
- `DriveItem`: `id, name, mime_type, size, modified, folder`
- API: none — `dynamic`, paths from the trigger's `items_at`/sample.

These are the field lists the trigger "Only when" builder offers, with operator sets filtered by field type (operator registry in `workflows/types.py`, design-definitions §8).

### 4.5 Schema revisions and drift

`schema_rev` = a short hash of the operation's `(params, result)` JSON Schema, computed at registry build. Definitions snapshot it at bind time (`OperationRef.schema_rev`, design-definitions §3.7). Validation compares:

- **Match** → fine.
- **Mismatch, compatible** (current schema accepts the saved bindings: only additions of optional params / new result fields) → silent auto-update of the snapshot on next save.
- **Mismatch, breaking** (a bound param renamed/removed/retyped; a referenced result field gone) → **warning** on the step ("this tool changed — re-map"), Save still allowed, the step fails cleanly at run time if executed un-remapped. The assistant is the remediation path ("fix this step").

Compatibility is computed structurally from the two schemas plus the actual bindings/refs in the definition — a breaking change that touches nothing the workflow uses is treated as compatible *for that workflow*.

### 4.6 The v1 operation set and the audit

The audit (engine spec §2 action) = enumerate the operations below, define each one's canonical params/result models to "workflow-grade" (stable names, correct types, required/optional marked), and reconcile the two broker families. Initial set, from the existing broker verbs:

| Operation | effect | Backing verbs | Audit notes |
|---|---|---|---|
| `email.list_messages` | read | `list_messages` / `search_messages` | unify list+search (optional `query`) |
| `email.get_message` | read | `fetch_message` | |
| `email.send_message` | write | `send_message` | attachments as file paths, encoded in the facade |
| `email.move_message` | write | `move_messages` | singular per-item form |
| `email.add_label` | write | — | **gap**: mockups use Label "triaged"; Gmail models labels as folders — needs either a `move_messages` mapping or a new broker verb. Audit decides. |
| `calendar.list_events` | read | `list_events` | |
| `calendar.create_event` | write | `create_event` | **gap**: Google broker only — IMAP/CalDAV broker's `create_event` unimplemented. Capability matrix per integration type, surfaced by the permission-aware picker. |
| `calendar.update_event` / `delete_event` | write | `update_event` / `delete_event` | Google only, same note |
| `drive.list_files` | read | `list_drive_files` / `search_drive_files` | unify |
| `drive.get_file` | read | `get_drive_file_metadata` / `export_drive_file` | metadata + content fetch |
| `drive.upload_file` / `move_to_trash` | write | `upload_drive_file` / `trash_drive_file` | |
| `contacts.list` | read | `list_contacts` / `search_contacts` | |
| `http.request` | read/write | `http_request` | `effect` derived from method (GET/HEAD read, else write); result `{status, headers, body, body_path}` with parsed-JSON body access for `items_at` traversal |

Not every broker verb becomes an operation (share_drive_file, create_drive_folder etc. can wait); every operation must clear the audit bar before it's mappable.

## 5. Structured agent output (absorbs the provider spec)

Carried decisions stand: the user only ever describes a shape; **opportunistic native + universal parse/validate/retry, N attempts, then a clean typed failure**; no capability gating — incapable models surface in the dry run.

### 5.1 Plumbing (the `chat()` change)

`Provider.chat()` / `chat_stream()` gain one optional param, default `None` (today's behavior untouched):

```python
response_schema: dict[str, Any] | None = None   # JSON Schema
```

Each adapter sets its native field when the param is present: Ollama `format`, OpenAI chat `response_format: json_schema`, OpenAI responses `text.format`, Anthropic `output_config.format`, Fake emits a schema-shaped fixture. Unknown OpenAI-compat endpoints: always attempt it — endpoints that ignore the field fall through to validation, which is the correctness mechanism anyway. The schema rides on `Agent` as an optional field so `run_turn` threads it through without signature churn.

### 5.2 The validate/retry loop lives in the agent-step executor

Not in the sdk turn loop. `run_turn` stays conversation-shaped (returns final text); the workflow agent-step executor (`design-engine.md`) wraps it:

1. Build the JSON Schema from the step's `ShapeField`s (§5.3) and a Pydantic model for validation (dynamic `create_model`).
2. Run the turn. Extract the candidate payload from the final text: strict parse first, then fenced-code-block extraction, then first-balanced-JSON-object scan.
3. Validate. Success → the typed value becomes the step result.
4. Mismatch → append a corrective user message to the same history — the expected shape plus the specific validation errors — and run another turn. Up to **N = 3 attempts total** (config knob `workflows.structured_output_attempts` in the YAML config, not user-facing).
5. Exhausted → fail the step with `schema_mismatch` (typed), carrying the last errors. Distinguished from `truncated` (`done_reason` length) and `refused` (no JSON candidate at all) so run history and the dry run say the right thing.

### 5.3 Shape → JSON Schema

Small converter in `workflows` (next to the shape types): object with all declared fields `required`, `additionalProperties: false`, `enum` for enum fields, `array` + flat-object `items` for lists, `format: date` annotation for dates (validated leniently — ISO date or datetime accepted). v1 sub-language stays minimal (no lengths/ranges/regex); we own validation, so expansion later is provider-independent.

### 5.4 Testing

- FakeProvider: schema-shaped fixtures; a misbehaving mode (returns prose, then valid on attempt k) for retry-loop tests.
- Per-adapter unit tests: native field constructed correctly from a schema.
- Loop tests: never-conforms → `schema_mismatch` after N; truncation → `truncated`; prose-wrapped JSON extracted.
- Facade: normalization tests per broker family from recorded fixture dicts; param validation rejects unknown fields; drift hash stability test (schema_rev changes only when the schema does).
- `compute_scope`: table-driven tests over graph topologies (branch, rejoin, multi-trigger, per-item).

## 6. Open questions

- `email.add_label` backing (broker verb vs move semantics) — audit decides; affects the canonical mockup workflow.
- Whether the facade exposes a generic `list/sample` entry point for trigger previews or reuses each read operation with a `limit` — leaning reuse.
- Date handling discipline across brokers (IMAP date strings vs Google RFC 3339) — normalization should canonicalize to ISO 8601 UTC; confirm during audit.
- Where the JSON-Schema-for-shape converter lives if the assistant also needs it client-side — likely server-only, assistant gets it via the scope API.
