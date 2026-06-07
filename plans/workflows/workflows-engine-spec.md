# Workflows Engine — Technical Spec (Skeleton)

> **Status:** Skeleton / notes only. Full design **not** written yet — sections
> are placeholders with `TODO(design)` markers. This is a holding place for
> engine-level technical concerns surfaced during requirements discussion, so
> they aren't lost or buried in the user-facing doc.
>
> **Scope:** the workflow engine's internal design (data flow, typing,
> persistence, versioning). User-facing behavior lives in
> `workflows-requirements.md`; the provider schema-enforcement work has its own
> doc, `provider-structured-output-spec.md`.

## 1. Data flow & step I/O typing

How data moves between steps and what's known about its shape.

- The run-wide data context: everything produced so far, addressable per step.
- Typing model: which step I/O is **typed** (has a schema) vs **free text**.
  - Tool/code step **inputs** are typed (defined schema) → visual field mapping
    points into them cleanly.
  - Many step **outputs are free text by design** — tool results, and agent
    results not given a defined shape. There are no fields to map *out of*; the
    text can only be taken as a whole value unless structure is produced
    explicitly (agent structured result, or a code step that parses).
- Agent steps: input is free-text instruction (no input schema pinned); a schema
  is pinned only on the **output** side, and only when a structured result is
  requested.

`TODO(design)`: the data-context representation, addressing scheme, and how a
field's shape (or lack of one) is computed for the editor/assistant and for
mapping validation.

## 2. Tool input schemas as a build-time contract

Consequence of no-code typed mapping: a saved workflow depends on the schemas it
maps into.

- When a step maps into a tool's typed inputs, the tool's **input schema becomes
  part of the workflow's definition contract** — no longer just the LLM's
  invocation hint (the docstring-derived schema), but a build-time dependency.
- Changing a tool's parameters (rename / remove / retype) is therefore a
  **breaking change** for any workflow that mapped into them, not just an internal
  refactor. Tool input schemas become a stability surface that needs API-like
  care.
- Only affects steps with typed inputs (tool/code steps). Agent steps don't pin
  an input schema (free-text instruction).

Two design hooks this implies:

- **(a) Drift is a versioning problem.** A saved mapping references a tool schema
  as of build time. This is the same class of problem as definition versioning /
  engine upgrades — a run pins to the definition it started with; tool-schema
  drift wants compatible handling. Cross-link the versioning/run-pinning design.
- **(b) Drift needs a user-facing signal.** Same shape as the broken-account
  warning: a step shows a clear warning when the tool it maps into no longer
  matches the saved mapping. (Behavior is user-facing; the detection mechanism is
  engine-side and belongs here.)

`TODO(design)`: how tool schemas are captured/snapshotted in a definition; how
drift is detected at load/validate/dry-run time; what "compatible vs breaking"
change means; remediation flow (re-map, assistant-assisted fix).

> **Action — one-time schema audit before committing the surface.** Before
> integration tools are exposed as a mappable, supported API surface for
> workflows, do a **one-time pass over every integration tool to ensure each has a
> solid, well-defined input schema** (correct types, required/optional marked,
> stable parameter names — not just a loose docstring-derived shape). Today these
> schemas exist primarily as LLM invocation hints; promoting them to a build-time
> contract (§2) means a sloppy schema becomes a sloppy public contract. Fix the
> weak ones first; only then commit to tools being mappable in workflows.

`TODO(design)`: define the bar a tool schema must clear to be "workflow-grade,"
and run the audit against the current tool set.

## 3. Definition versioning & run pinning (cross-reference)

Carried decision: definitions are versioned; runs pin to the definition they
started with; lazy forward-migration on load; bounded compatibility window. The
tool-schema-contract concern in §2 folds into this.

`TODO(design)`: unify §2 drift handling with the definition-versioning mechanism
rather than designing two separate systems.

## 4. Open technical questions

`TODO(design)`: collect as design proceeds — e.g. snapshot granularity (whole
definition vs per-referenced-tool-schema), whether tool schemas are versioned
independently of the tool registry, how the editor surfaces a "shape unknown"
source (free-text output) during mapping.

---

## Resolved decisions (carried from discussion)

- **Mapping asymmetry is inherent.** Typed inputs map cleanly; free-text outputs
  have no fields to map out of — structure is produced via a structured agent
  result or a code step, not invented by the mapper. (§1)
- **Typed mapping makes tool input schemas a contract.** Saved workflows depend
  on them; schema drift is breaking and is handled as part of definition
  versioning, with a broken-step warning as the user-facing surface. (§2, §3)
