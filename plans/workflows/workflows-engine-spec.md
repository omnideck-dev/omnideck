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
- **(b) Drift needs a user-facing signal.** Same shape as the broken-integration
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

## 4. Data references between steps (two mechanisms, no inline tokens)

How a step consumes earlier data. There are **two** mechanisms, split by the
hard/soft input distinction — and deliberately **no inline `{token}`s spliced into
prose**, which avoids the inline-vs-attach size heuristic entirely.

- **Tool / code step → field mapping (hard).** Each typed input is bound to exactly
  one value (`To = New email ▸ sender`). The resolved value is passed as a typed
  argument; types validated. Precise, because a tool argument must be exactly one
  thing.
- **Agent step → an "include" list (soft).** The instruction stays **plain prose**.
  The user **checks which upstream outputs to include**; the engine hands those to
  the agent as **labeled, quarantined `<data>` context blocks**. The agent reads
  them; its *use* is non-deterministic (soft input). Hard guarantees on an agent
  are on the **output** side (the return shape — see
  `provider-structured-output-spec.md`). Nothing is inlined, so there is **no
  size/type heuristic** to get right.

Common to both:

- **A reference is structured, not a string** — `{stepId, fieldPath}` (or the
  trigger as source), shown as a chip / checklist row; survives renames; validated.
- **Build-time scoping.** Only data **reachable at that point in the graph** is
  offered (trigger + steps before this one on this path; the loop `item` inside a
  loop; run context). Field-level references require the upstream step to have a
  **declared shape**; an un-shaped output is referenceable only as its whole
  `(text)` value. (Ties to §1 typing, §2 schema-as-contract; full scope rules in
  the data-picker mockup.)
- **Validation.** A reference whose target step/field no longer exists is
  **dangling** → broken-reference / broken-include warning on the step (same family
  as broken-integration / tool-schema-drift). Referenced fields are a dependency of
  the saved definition.
- **Quarantine.** Included/mapped content is often untrusted (email body, web
  result) → always delivered as delimited `<data>` blocks, treated as data not
  instructions (prompt-injection safety).
- **Missing at runtime** (null, skipped branch) → the step's failure policy applies
  (retry → stop / error-path / skip). Dry-run surfaces missing/broken refs first.

`TODO(design)`: the reference object format and addressing; available-data
computation from graph topology; the picker's shape introspection (typed vs
`(text)`); inline-vs-attached threshold; the quarantine/delimiting format for
injected data; broken-reference detection + remediation (shared with §2/§3).

## 5. Watch-trigger condition evaluation

The "only when" filter on a watch trigger.

- A condition is a **deterministic rule** over the watched item's fields —
  `field → operator → value`, combined with ALL/ANY (same builder as a Branch
  step). It is **evaluated per item, per poll, without an LLM** — fuzzy judgement
  belongs in an agent step inside the workflow, not the trigger filter.
- **Fields are tool-supplied.** The available fields and their types come from the
  watched tool's item shape (email: `from/to/subject/folder/date`; drive:
  `name/mimeType/size/modified/parents`; calendar: `summary/start/end/...`;
  contacts: `name/emails/organization/title`). Operators are filtered by field
  type (text / list / date / number / enum).
- **APIs have no fixed shape** → fall back to an **expression** over the response
  body (the escape hatch).
- Evaluation order per poll: poll → dedup (new items only) → condition filter →
  volume cap/overflow → one run per item (or batch).

`TODO(design)`: the rule representation (shared with Branch); per-tool field/type
introspection for the builder; the expression evaluator for API/JSON; dedup-key
selection per tool (uid/id); where the rule engine runs.

## 6. Open technical questions

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
- **Two data-reference mechanisms, no inline tokens.** Tool/code use **field
  mapping** (hard typed binding, one value per input). Agent steps keep a **plain
  instruction** + an **"include" checklist** of upstream outputs, delivered as
  labeled quarantined `<data>` context (soft input). This drops the inline-vs-attach
  size heuristic entirely. Both are structured `{stepId, fieldPath}` refs,
  graph-scoped and validated; hard agent guarantees are output-side (return shape).
  (§4)
- **Watch conditions are deterministic per-item rules** over tool-supplied fields
  (same builder as Branch), no LLM in the filter; APIs fall back to an expression.
  Fuzzy judgement goes in an agent step. (§5)
