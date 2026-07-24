# Workflows — High-Level Architecture

The UX is specified by the mockups in `plans/workflows/mockups/` (the deck is the walkthrough); `workflows-requirements.md` supplements them where a mockup can't speak. This document maps that UX onto the existing repo: new packages, major components, their responsibilities and interactions. Each major component gets its own low-level design doc (listed at the end).

## 1. Where it sits in the repo

```
workflows/                  NEW — top-level package (peer of tasks/, agents/, sdk/)
  definitions: model + store + versioning
  engine: run executor, step executors, dry-run
  triggers: schedule + watch pollers, trigger state
  assistant: draft-editing ops the assistant calls
server/
  _workflow_routes.py       NEW — REST surface, registered like every other feature
server/ui/src/
  components/workflows/     NEW — all workflow components in their own folder
                            (list/overview, builder, inspector editors, dry run)
  hooks/useWorkflows.js     NEW
integrations/               EXTENDED — typed operations facade over the broker clients
                            (the step-facing shim; workflow-agnostic, lives here)
tools/integrations/         UNCHANGED initially — later refactors into prose adapters
                            over the facade so each operation has one contract
sdk/, agents/               REUSED — agent steps run through build_agent + run_turn
tasks/                      REPLACED eventually — Goals stays until Workflows lands
```

State lives in `~/.computron_9000/workflows/` as JSON with atomic temp+rename writes, same as `tasks/_file_store.py`. The runner starts in the deferred-subsystems phase of `server/aiohttp_app.py` startup, gated by a feature flag in `config/`, exactly like the Goals task runner.

## 2. Major components

### 2.1 Definition model & store (`workflows/definitions`)

The workflow definition is the artifact everything else consumes: trigger(s), steps (agent / tool / code / branch / approval), edges (including named branch paths), per-step config, and data references between steps. Pydantic models, JSON on disk.

Responsibilities:
- Schema for every step type and trigger kind shown in the mockups (step-config.html is the catalog of what must be expressible).
- **Versioning**: saving produces a new immutable version; runs pin the version they started on (engine spec §3). Edits never mutate a version a run is using.
- **Pending changes**: assistant proposals (and nothing else) exist as a draft diff against the current version — applied atomically or discarded. This is a store concept, not a UI trick, so the EDIT badge / pending field tint / change card all render one state.
- Validation: references point at steps that exist and are upstream; branch paths are exhaustive (default path); per-item sources are list-typed.

### 2.2 Step I/O & data references (`workflows/definitions`, shared types)

The typed-data backbone (engine spec §1, §4). Every step declares what it produces; references (`Triage ▸ tasks`, `item ▸ due`) resolve against upstream shapes at build time and against actual values at run time.

- Agent steps: optional declared shape (with enums) → structured output via the provider work in `provider-structured-output-spec.md`; shape off → text.
- Tool steps: input/output schemas as a build-time contract (engine spec §2). Steps do **not** call the LLM-facing tool functions in `tools/integrations/` — those have prose docstrings and flatten results to strings for an agent to read. Instead, a **typed operations facade in `integrations/`** wraps the broker/supervisor clients directly: typed params, typed result models (the broker RPC layer already passes dicts, and broker `types.py` models exist to build on — the string-flattening only happens at the tool layer). It lives in `integrations/`, not `workflows/`, because it's workflow-agnostic — tool steps, watch triggers, and trigger previews all consume it, and `tools/integrations/` later refactors into thin prose adapters over it so each operation has one contract with two presentations (typed for steps, prose for agents). The **schema audit** of `tools/integrations/` is the prerequisite that defines the facade's contracts.
- Code steps: run in the existing Podman sandbox; references are inputs injected by name, the last expression is the output.
- Scope rules: what the data picker shows (trigger + upstream + `item` inside per-item + run context) is computed from the definition graph — one function used by the UI picker, the assistant, and validation.

### 2.3 Engine (`workflows/engine`)

The run executor. Walks the pinned definition version, executes steps, persists state after every transition so the process can restart mid-run.

- **Run lifecycle**: a Run row (status, current step cursor, per-step results) stored like Goals runs. Every step result persisted before advancing — pause/resume and crash recovery fall out of this.
- **Step executors**, one per type:
  - *Agent*: `build_agent(profile, tools)` → `run_turn()`; instruction + included context assembled into the turn; structured result parsed against the declared shape.
  - *Tool*: direct async call through the typed operations facade (2.2) with mapped inputs — never through an LLM, never the prose-returning agent tools. Per-item mode fans out over the list source, one call per element, results collected in order.
  - *Code*: sandboxed execution with injected references.
  - *Branch*: evaluate path rules (or expression) against resolved references; route to the named edge.
  - *Approval*: persist the run as `waiting`, send the ask via the configured tool (Telegram etc.), resume on approve/reject via API callback. No timeout.
- **Failure handling** per the requirements: step failure policy, retries, run-level notification via tools.
- **Dry run is the same executor** in a different mode: seeded from a picked trigger match, advances one step per user action, write tools previewed instead of fired (unless run-for-real), outputs editable in place — an edited output replaces the step result and downstream steps resolve against it, branch rerouting included. Dry-run sessions are server-side state with a small stepping API; they never write trigger dedupe state.

### 2.4 Triggers (`workflows/triggers`)

A scheduler loop in the Goals-runner style (poll interval, croniter already a dependency) plus per-trigger watchers.

- **Schedule**: days-of-week + time (no cron in the UI; croniter underneath or plain time math). Manual run = "now".
- **Watch (new item)**: poll the integration via the same typed operations facade steps use; evaluate field conditions (engine spec §5); dedupe by stable id persisted per trigger.
- **Watch (changed item)**: scoped to a picked list of items; persist each item's id + watched-field value; fire on change. Email is new-only; calendar/drive support changed; API triggers support both with user-picked paths (items-at / identify-by / watch field) evaluated against the polled response.
- Trigger state (dedupe sets, changed-item snapshots, last-poll cursors) lives next to the workflow's runs, versioned independently of the definition.

### 2.5 Assistant integration (`workflows/assistant`)

Both assistant surfaces are the same mechanism at different scope: an agent (via sdk) whose tools operate on a **draft definition**, producing pending changes the user applies.

- Ops exposed as tools: read the definition + scopes, propose add/edit/remove of steps and fields, run a sample API call (the real `call_api` tool), read upstream shapes. Proposals land in the pending-changes store (2.1) — never directly in the saved definition.
- Workflow panel: conversational, whole-definition scope, multi-change proposals (plan drafts, grow-the-flow), change cards with inline before/after.
- In-editor ✦: one-shot, scoped to a single step's fields; same proposal objects, rendered as pending field values. Apply (panel) and Keep (editor) commit the same pending change.

### 2.6 REST API (`server/_workflow_routes.py`)

Following the existing `register_*_routes` pattern:
- Definitions: CRUD, versions, validate.
- Pending changes: list / apply / discard.
- Runs: list, detail (per-step results), cancel; approval resolve (approve/reject callback target).
- Dry run: open session (workflow + picked trigger match), step forward/back, edit a step output, re-run a step, toggle run-for-real, close.
- Triggers: sample poll (for the trigger preview and API "Run sample"), trigger-state inspection.
- Assistant: message endpoint streaming events (reuses the chat streaming JSONL pattern).

### 2.7 UI (`server/ui/src`)

New top-level view wired the way every view is: `Sidebar.jsx` entry, `view === 'workflows'` in `DesktopApp.jsx`, `useWorkflows` hook for data. Unlike the existing flat `components/` directory, all workflow components (and their CSS modules) live in `components/workflows/` — the feature is big enough to warrant its own folder. The mockups map to components roughly as: index.html → list + overview; builder/step-builder → full-screen builder (canvas, palette, inspector); step-config → the inspector's per-type editors; data-picker → the shared reference picker; dry-run → the dry-run mode of the builder; assistant-experience / inline-assistant → the panel and the in-editor dock. Builder state (draft definition, selection, pending changes) is a reducer like `useAgentState`. SIGNAL tokens come from the design language; the `--assistant` token from the reskinned inline mockup is the one palette addition.

## 3. Cross-cutting decisions

- **Reuse over invention**: agent steps are ordinary sdk turns; tool steps call the same functions the LLM would; storage and runner patterns copy `tasks/`; the API and UI follow the established feature shape.
- **Typed boundaries are the new work**: structured agent output (provider spec), typed tool results (schema audit), and reference resolution are what make field conditions, branch rules, mappings, and per-item fan-out possible. Everything visible in the mockups that names a field depends on this layer.
- **One pending-state model**: assistant proposals are store-level pending changes; every surface (canvas badge, panel card, editor tint) is a view of that one record.
- **One executor**: dry run, real runs, and step re-runs inside a dry run are the same code path with policies (hold writes, manual advance) — never a parallel implementation.
- **Goals**: Workflows ships behind a feature flag alongside Goals, then replaces it; no automated migration of goals (they're text instructions — users recreate as workflows).

## 4. Low-level design docs to produce (one each)

These replace the existing spec skeletons: `workflows-engine-spec.md` folds into designs 1–4 (its sections map to definitions §3, step-io §1/§2/§4, engine §1, triggers §5, plus its resolved-decisions list), and `provider-structured-output-spec.md` folds into design 2. Each spec file is deleted once the design doc that absorbs it lands.

1. `design-definitions.md` — definition schema, versioning, pending changes, validation.
2. `design-step-io.md` — typed step I/O, reference model, scope computation; the typed operations facade in `integrations/` and the schema audit that defines its contracts; absorbs `provider-structured-output-spec.md`.
3. `design-engine.md` — run lifecycle/persistence, step executors, failure policy, approval pause/resume, dry-run sessions.
4. `design-triggers.md` — scheduler, watch pollers, per-kind trigger state, API trigger sampling.
5. `design-assistant.md` — assistant ops/tools, proposal objects, panel + in-editor flows.
6. `design-api.md` — full REST surface with request/response shapes.
7. `design-ui.md` — component tree, builder state model, mockup→component mapping.

Suggested order: 1 → 2 → 3 (these three gate everything), then 4–7 in any order; implementation can start on definitions + step I/O while later designs are written.
