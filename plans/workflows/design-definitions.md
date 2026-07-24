# Design — Definitions: model, store, versioning, pending changes, validation

Low-level design for `workflows/definitions` (architecture §2.1). Source of truth for UX is the mockups; `step-config.html` is the catalog of everything the schema must express. Absorbs `workflows-engine-spec.md` §3 (versioning & run pinning). Reference *semantics* (scope rules, shape introspection, drift) live in `design-step-io.md`; this doc defines how references and schemas are **stored**.

Known divergences from `workflows-requirements.md` (mockups win): no Loop step (per-item is a tool-step run mode); no single-step testing (dry run only); watch triggers pin **one** integration in v1 (multi-integration watch deferred).

## 1. Package layout

```
workflows/
  __init__.py            — facade, re-exports only
  types.py               — leaf module: all Pydantic models below (stdlib + pydantic only)
  definitions/
    __init__.py          — facade
    _store.py            — file store: workflow meta, draft, versions, pending changes
    _validate.py         — structural validation (errors/warnings)
    _ops.py              — pending-change op application (diff/patch against a draft)
```

`workflows/types.py` is dependency-free so the engine, triggers, assistant, server routes, and `integrations` facade can all import it without cycles.

## 2. Storage layout

```
~/.computron_9000/workflows/
  {workflow_id}/
    workflow.json        — WorkflowMeta
    draft.json           — Draft (working definition + draft_rev)
    versions/{n}.json    — immutable WorkflowVersion snapshots
    pending.json         — the open PendingChange (and the last resolved one)
    assistant/           — panel thread (design-assistant.md)
    runs/                — design-engine.md
    trigger-state/       — design-triggers.md
```

All writes atomic temp+rename, same pattern as `tasks/_file_store.py`. One store instance owns the directory; no cross-process writers (the aiohttp app is the only writer).

## 3. Core models

All models in `workflows/types.py`, Pydantic, JSON-serialized. Ids are short random slugs, generated once, never reused; display names are separate fields so **references point at ids and survive renames**.

### 3.1 Containers

```python
class WorkflowMeta(BaseModel):
    id: str
    name: str
    enabled: bool            # master switch: False = triggers never fire (manual run still allowed)
    created_at: str          # ISO 8601, as in tasks/_models.py
    updated_at: str
    latest_version: int      # 0 = never saved
    draft_rev: int           # monotonically increasing, bumped on every draft edit

class Draft(BaseModel):
    draft_rev: int
    definition: Definition

class WorkflowVersion(BaseModel):
    version: int             # 1..N, immutable once written
    created_at: str
    definition: Definition
```

### 3.2 Definition (the graph)

```python
class Definition(BaseModel):
    triggers: list[Trigger]            # 0..n; a workflow with none is manual-only
    steps: list[Step]
    edges: list[Edge]
    notifications: list[NotificationRule]

class Edge(BaseModel):
    source: str              # trigger id or step id
    path: str | None         # branch path name; None for single-output nodes
    target: str              # step id
```

Explicit edges (not implicit ordering) because branches split, paths can rejoin, and error paths (failure policy `error_path`) are edges with `path="error"`. The graph must be a DAG; rejoins are ordinary multiple-in-edges. Canvas positions are **not stored** in v1 — layout is computed (mockups are auto-laid-out left-to-right); revisit only if manual arrangement becomes a requirement.

### 3.3 Data references and bindings (storage form)

```python
class DataRef(BaseModel):
    source: str              # trigger id | step id | "item" | "run"
    path: list[str]          # field path, [] = whole output; e.g. ["tasks"] or ["customer","email"]

Binding = DataRef | Literal  # tool/code inputs
class Literal(BaseModel):
    value: str | int | float | bool
```

`"item"` is valid only inside a per-item tool step (validation enforces). `"run"` is run context (started-at, workflow name, trigger kind). Semantics — what's in scope where, how shapes resolve, `(text)` whole-value fallback — are `design-step-io.md`.

### 3.4 Conditions (shared rule model)

One rule model shared by watch-trigger filters and branch paths (engine spec §5 carried decision):

```python
class Condition(BaseModel):
    field: str               # item field name (triggers) — or —
    ref: DataRef | None      # branch: the value under test
    op: str                  # type-filtered: is, is_not, is_one_of, contains, before, after, gt, lt, …
    value: str | list[str]

class ConditionGroup(BaseModel):
    match: Literal["all", "any"]
    conditions: list[Condition]
```

### 3.5 Triggers

Discriminated union on `kind`. Each watch trigger is one **integration × event kind** (the trigger model settled in the mockups); a workflow may have several triggers.

```python
class ScheduleTrigger(BaseModel):
    id: str; name: str; kind: Literal["schedule"]
    days: list[str]          # ["mon","tue",...] — multi-select, no cron in the model
    time: str                # "07:00"
    timezone: str

class WatchTrigger(BaseModel):
    id: str; name: str; kind: Literal["watch"]
    integration_id: str      # pinned, one (v1)
    source: WatchSource      # union below
    event: Literal["new", "changed"]
    conditions: ConditionGroup | None    # "Only when"
    interval_minutes: int    # "Check every"
```

Every match is its own run — there is no batch mode in v1 (the requirements doc's `single_run` option never made it into the mockups, and a list-shaped trigger output would change scope semantics everywhere). The fan-out safety cap is a fixed engine default, not definition config (`design-engine.md`).

`WatchSource` per integration type, carrying what the mockups configure:

- `EmailSource(folder)` — new only (email is immutable; `event="changed"` invalid).
- `CalendarSource(calendar_id)` — new or changed.
- `DriveSource(folder_id)` — new; changed requires `picked_items: list[PickedItem]` (id + display label) — changed-watch is scoped to a picked list, never broad polling.
- `ApiSource(method, path, items_at, identify_by, watch_field, request_body?)` — paths are dotted strings into the sampled response (`"data.orders"`, `"customer.email"`); `items_at` may point at a single object (one item; `identify_by` unused). The trigger's "Only when" for API uses the expression form of `Condition` over item fields. A sample response is **not** stored in the definition — sampling is a live action (trigger preview / assistant); only the chosen paths persist.

Manual run is not a trigger (requirements §3); it's an API action on the workflow.

### 3.6 Steps

Discriminated union on `type`. Common envelope:

```python
class StepBase(BaseModel):
    id: str
    name: str                # display name, referenced nowhere
    failure: FailurePolicy   # retries: int = 0; on_failure: stop | error_path | skip

class AgentStep(StepBase):
    type: Literal["agent"]
    profile_id: str          # AgentProfile id (agents/_agent_profiles.py)
    instruction: str         # plain prose — never contains inline tokens
    include: list[DataRef]   # "Include as context" — delivered as quarantined <data> blocks
    shape: list[ShapeField] | None   # None = free text result

class ShapeField(BaseModel):
    name: str
    type: Literal["text", "number", "boolean", "date", "enum", "list"]
    enum_values: list[str] | None      # type == enum
    item_fields: list[ShapeField] | None  # type == list; v1: flat scalar fields only (depth 1)

class ToolStep(StepBase):
    type: Literal["tool"]
    operation: OperationRef  # which facade operation (see 3.7)
    integration_id: str
    run_mode: Literal["once", "per_item"]
    for_each: DataRef | None # required iff per_item; must resolve to a list
    inputs: dict[str, Binding]   # operation param name -> binding

class CodeStep(StepBase):
    type: Literal["code"]
    source: str              # the program text; result of last expression = output
    inputs: dict[str, DataRef]   # variable name -> ref

class BranchStep(StepBase):
    type: Literal["branch"]
    mode: Literal["rules", "expression"]
    paths: list[BranchPath]  # ordered, first match wins
    default_path: str        # always present; the "Otherwise" edge name
    expression: str | None   # expression mode: evaluates to a path name
    expr_inputs: dict[str, DataRef]  # expression mode's @ refs

class BranchPath(BaseModel):
    name: str                # the edge label; unique within the step
    rule: ConditionGroup | None  # None in expression mode

class ApprovalStep(StepBase):
    type: Literal["approval"]
    show: list[DataRef]      # "Show me"
    ask_via: ToolInvocation | None   # delivery (e.g. Telegram); in-app always available, so optional
    # on_approve = continue, on_reject = stop run: fixed in v1, not stored
```

Code steps store **no inline tokens**: the `@`-pills in the editor are renderings of `inputs` variable names occurring in `source`. Inserting a pill = add an `inputs` entry (name auto-derived from the ref, de-duplicated) + splice the name into the text. This keeps the engine-spec "no inline tokens" rule uniform: prose instructions use `include`, code uses named inputs, tool params use bindings.

### 3.7 Tool operation references and schema snapshots

```python
class OperationRef(BaseModel):
    operation: str           # facade operation id, e.g. "calendar.create_event"
    schema_rev: str          # the operation schema revision captured at bind time

class ToolInvocation(BaseModel):     # shared by notifications and approval delivery
    operation: OperationRef
    integration_id: str
    inputs: dict[str, Binding]
```

`schema_rev` is the versioning hook from engine spec §2: the typed-operations facade publishes a revision per operation schema; a saved binding records what it mapped against. Drift detection and the compatible/breaking rules are `design-step-io.md`; the definition's only job is to carry the snapshot.

### 3.8 Notifications

```python
class NotificationRule(BaseModel):
    event: Literal["run_failed", "run_finished"]
    action: ToolInvocation
```

No dedicated notification system — a rule is a tool invocation (requirements §3). New workflows get a `run_failed` rule scaffolded (on by default) once the user picks a delivery tool; needs-approval delivery is per approval step (`ask_via`), not a rule here.

## 4. Versioning & run pinning

- **The draft is the only mutable definition.** Every editor or assistant change lands in `draft.json` and bumps `draft_rev`. The builder's UNSAVED pill = `draft != versions/{latest_version}` (tracked with a `dirty` flag rather than deep compare).
- **Save = validate + snapshot.** Save runs validation (errors block, §6); on pass, writes `versions/{N+1}.json` (immutable), sets `latest_version = N+1`. Nothing else changes — saving doesn't touch runs.
- **Runs pin a version.** A run records `(workflow_id, version)` at start and reads only that snapshot for its whole life — in-flight runs finish on the definition they started with; the next run picks up edits (carried decision). Approval pauses can outlive many saves safely.
- **Triggers fire the latest saved version**, and only when `enabled` and the workflow has ≥1 saved version. The draft is never executed by triggers; the dry run executes the **draft** (that's its point).
- **Retention:** versions referenced by retained runs + `latest_version` are kept; older ones GC'd lazily when runs are pruned. No user-facing version history (requirements §9) — this is internal pinning only.
- **No migration machinery in v1.** Definitions carry a `schema_version` int at the top of each file; the existing `migrations/` system handles format evolution the way it does for other stores.

## 5. Pending changes (assistant proposals)

The store-level mechanism behind every assistant proposal surface (pending field tint, EDIT/NEW node badges, panel change cards). Only the assistant creates these; direct user edits go straight to the draft.

```python
class PendingChange(BaseModel):
    id: str
    base_draft_rev: int      # the draft rev the ops were computed against
    origin: Literal["panel", "dock"]
    step_scope: str | None   # dock: the step id it's confined to
    summary: str             # the assistant's one-line description
    ops: list[Op]
    status: Literal["open", "applied", "discarded", "stale"]
    created_at: str

Op = AddNode | RemoveNode | PatchNode | SetEdges | AddTrigger | PatchTrigger | AddNotification
class PatchNode(BaseModel):
    op: Literal["patch_node"]
    node_id: str
    field: str               # dotted field path within the step model
    old: Any                 # value at proposal time — drives the WAS/NOW diff and staleness checks
    new: Any
```

Rules:

- **At most one open PendingChange per workflow.** The per-workflow assistant turn lock already serializes creation; a new proposal replaces the open one (dock follow-ups **revise ops in place** — the proposal is the state, there is no proposal history). Resolved proposals are kept only as the panel thread's inert cards (`applied`/`discarded` label), not as store records beyond the last one.
- **Apply is atomic and rev-guarded.** If `base_draft_rev == draft_rev`: apply all ops, bump `draft_rev`, mark `applied`. If not (user edited the draft meanwhile): mark `stale`; the UI shows the card as outdated and the assistant re-proposes on request. No merging.
- **Apply (panel) and Keep (dock) are the same call.** Undo/Discard marks `discarded` without touching the draft — nothing to roll back because ops never touched the draft before apply.
- **Ops carry `old` values** so the panel renders WAS/NOW without recomputing, and so staleness is detectable per-field if we later want finer-grained conflict handling (v1: rev-level only).
- **Applying may leave the draft invalid** (e.g. a proposed plan with a step the user must finish configuring). Draft tolerance is the rule (§6); Save remains the gate.

## 6. Validation

`_validate.py` takes a `Definition` and returns `list[Finding]` where `Finding = {severity: error|warning, node_id|trigger_id|None, code, message}`. Pure function of the definition + the operation-schema registry (for input completeness); no I/O.

**Errors (block Save; draft may carry them):**
- Graph: unknown edge endpoints; cycles; unreachable steps; branch step missing `default_path` or duplicate path names; edge `path` naming a nonexistent branch path; `error` edges from a step whose policy isn't `error_path`.
- References: `DataRef.source` not an existing trigger/step/`item`/`run`; ref target not upstream of the referencing step (scope computation from `design-step-io.md`); `item` used outside a per-item step; `for_each` missing on per-item or not list-typed (when the upstream shape is known).
- Steps: agent `profile_id` unknown; tool `operation` unknown to the facade registry; required operation inputs unbound; approval with empty `show`; schedule trigger with no days; drive changed-watch with empty `picked_items`; email trigger with `event="changed"`.
- Shapes: duplicate field names; enum with no values; list fields nested beyond depth 1.

**Warnings (Save allowed; shown on the step):**
- Broken integration (disconnected / missing permission) — recomputed live, not stored.
- Tool-schema drift: `schema_rev` no longer current (semantics in `design-step-io.md`).
- Empty agent instruction; unbound optional inputs the operation marks recommended; no `run_failed` notification rule.

**When it runs:** on every draft write (findings returned to the editor and cached on the draft for cheap reads), on Save (errors gate), on pending-change apply (findings refresh but don't gate), and on trigger enablement (workflow with error findings can't be enabled).

## 7. Store API (internal)

`_store.py`, async, mirroring `tasks/_file_store.py` conventions:

```
list_workflows() / get_meta(id) / create(name) / rename / delete / set_enabled
get_draft(id) -> Draft
update_draft(id, mutate_fn, *, expected_rev) -> Draft        # rev-guarded, bumps draft_rev
save_version(id) -> WorkflowVersion                          # validates, snapshots
get_version(id, n) -> WorkflowVersion
get_pending(id) / put_pending(id, change) / resolve_pending(id, status)
apply_pending(id) -> Draft                                   # the atomic rev-guarded apply
```

`expected_rev` is the optimistic-concurrency guard the REST layer exposes (editor and assistant both go through it; a stale writer gets a 409 and refetches).

## 8. Resolved questions

- **Edge identity**: edges have no ids and ops don't address them individually — `SetEdges` replaces the whole list; diffs for display are computed old-vs-new. Revisit only if proposals get noisy.
- **Batch mode**: dropped from v1 (see §3.5). One match = one run; safety cap is an engine default.
- **Operator vocabulary**: a small static registry in `workflows/types.py` next to the `Condition` model, keyed by field type — trigger filter UI, branch UI, and validation all read the same table; the evaluator lives in the engine.
- **Approval response wiring**: the definition stores only `ask_via` (delivery). Detecting a reply and matching it to the paused run is engine/broker mechanics (`design-engine.md`); no user-facing response config.
