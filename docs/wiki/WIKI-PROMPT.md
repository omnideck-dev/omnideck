# Omnideck Codebase Wiki — Maintenance Prompt

You maintain a navigable, commit-pinned wiki describing Omnideck's architecture, code
entities, and recurring patterns. Unlike a changelog or a design doc, this wiki is
generated *from the source itself* — every page traces to the files it describes and
records the commit it was last checked against. The goal: an AI agent or a new
contributor should be able to answer "how does X work" or "where do I add Y" from the
wiki alone, without reading the whole codebase, and should be able to tell at a glance
whether a page might be stale.

This file lives at `docs/wiki/WIKI-PROMPT.md`. It replaces an earlier version of this
file that described a different, source-ingestion-based wiki (raw docs → summary pages).
That schema was abandoned in favor of the one below, which reads code directly instead
of requiring the user to feed in documents.

## Vault layout

```
docs/wiki/
  WIKI-PROMPT.md     # this file
  .state.yml          # { last_commit, last_run, schema_version }
  index.md            # catalog of every page, by category
  codemap.md          # directory-by-directory map: path → purpose → wiki page
  overview.md         # one-page orientation: what the project is, how the pieces fit
  glossary.md         # short-definition lookup for domain terms, cross-linked
  log.md              # append-only history of wiki update runs
  entities/           # one page per concrete thing: a class, function, module, route set
  concepts/           # one page per mechanism or architectural idea
  patterns/           # one page per "how do I add/extend X" recipe
  guides/             # user-facing, non-code-mapped docs (workflows, use cases)
```

`entities/`, `concepts/`, and `patterns/` pages are code-mapped: every one pins a commit
and a list of paths. `guides/` pages are not — they describe how to *use* Omnideck, not
how the code implementing it works, and don't need `verified_commit`/`paths`.

## Page format

### Code-mapped pages (`entities/`, `concepts/`, `patterns/`)

Frontmatter:

```yaml
---
title: Page Title
type: entity | concept | pattern
tags: [relevant, tags]
created: YYYY-MM-DD
updated: YYYY-MM-DD
verified_commit: <short-sha>   # HEAD at the time this page's content was last confirmed accurate
paths:
  - "path/to/thing.py"         # every file this page's claims depend on
  - "path/to/package/"
---
```

`verified_commit` is the freshness signal. It is **not** "when the page was last edited"
— it's "the commit at which someone (you) last checked this page's claims against the
actual code at these `paths` and found them still true." A page can go untouched for
months and still carry a recent `verified_commit` if nothing under its `paths` changed.

Body sections, by type:

- **Entity** (`entities/{Name}.md`): `## Overview`, `## Location`, `## Details`
  (fields/behavior — a table if it's a data model), `## Key Functions` or `## Key
  Methods`, `## Related Entities`, `## Sources` (non-code docs that informed it, if any).
- **Concept** (`concepts/{Name}.md`): `## Overview`, `## How It Works` (numbered flow,
  or sub-headed stages), `## Where It Lives` (file → role table), `## Key Details`
  (bullets — invariants, gotchas, non-obvious behavior), `## Open Questions` (things you
  couldn't confirm from code alone), `## Sources`.
- **Pattern** (`patterns/{Name}.md`): `## Overview`, `## Where It's Used`, `## How to
  Extend This` (numbered steps, with real code), `## Deviations From Textbook Form`
  (where this codebase's convention differs from the generic version), `## Related
  Concepts`.

Shared rules:

- Use Obsidian `[[wikilinks]]` for every reference to another wiki page. Link liberally.
- Keep pages focused — one entity/concept/pattern per page. Split past ~300 lines.
- Every file path, function name, and line-level claim must come from actually reading
  the file at that path — never guess or extrapolate from a similar-looking file
  elsewhere, and never carry a claim forward from an old page without re-checking it
  against current source.
- If a page's subject has been renamed or restructured since its last `verified_commit`,
  say so in the page rather than silently rewriting history — a line like "Formerly
  `sdk/turn/`, moved to `agent_core/turn/` in <context>" helps a reader (or an agent)
  who has the old name in mind.

### Index pages

- **`index.md`**: tables of all Entities / Concepts / Patterns (and Sources, if any
  non-code docs were consulted), each row linking to the page and showing its
  `verified_commit`.
- **`codemap.md`**: one row per top-level directory (or notable subpackage): path,
  one-line purpose, key entry-point files, and which wiki pages cover it. Also keep a
  "Where to look for common tasks" table and an "Entry points" list (server start, main
  HTTP routes, frontend root, test runner, config).
- **`overview.md`**: what the project is, an architecture diagram (ASCII is fine), a
  short "Key concepts" glossary-in-miniature, the tech stack table, and a "Where to go
  next" list of links. This is the front door — assume a reader starts here.
- **`glossary.md`**: flat alphabetical list of short definitions, each linking to the
  fuller page. No frontmatter needed.

### `.state.yml`

```yaml
last_commit: <short-sha>   # HEAD as of the most recent wiki update run
last_run: <ISO 8601 timestamp>
schema_version: 1
```

### `log.md`

Append-only. One entry per update run:

```markdown
## [YYYY-MM-DD] <kind> | <commit-range or commit>

- What triggered this run and its scope (full regen vs targeted refresh)
- Pages created: [[page1]], [[page2]]
- Pages updated: [[page3]], [[page4]]
- Pages removed/merged, with why (renamed, deleted, superseded)
```

## Update workflow

When asked to update the wiki (or when the gap between `.state.yml`'s `last_commit` and
current `HEAD` looks large):

1. **Measure staleness.** `git rev-list --count <last_commit>..HEAD` and `git diff
   --stat <last_commit>..HEAD`. A handful of commits touching a couple of modules →
   targeted refresh. Dozens of commits, renamed top-level packages, or hundreds of
   changed files → treat it as a full regeneration: re-survey the directory tree fresh
   rather than trusting the existing page list to still match reality.
2. **Targeted refresh** (small staleness): for each existing page, run `git diff --stat
   <page's verified_commit>..HEAD -- <page's paths>`. Empty diff → the page is still
   accurate; bump `verified_commit` to current `HEAD` without rewriting content.
   Non-empty diff → re-read the current source at those paths and rewrite the affected
   sections.
3. **Full regeneration** (large staleness): re-walk the source tree top to bottom.
   Confirm each existing page's subject still exists at the path recorded — if the
   package was renamed or split, note that explicitly and point the page at its new
   location (or split it to match, if the split was real). Look for whole subsystems
   with no page yet (new top-level packages, new tool categories, new route groups) and
   create them. Remove pages whose subject no longer exists, folding anything still
   true into whatever replaced it.
4. **Update the index.** Refresh `index.md`, `codemap.md`, `overview.md`, and
   `glossary.md` to match the final page set.
5. **Bump `.state.yml`** to the current `HEAD` short-sha and current timestamp.
6. **Append to `log.md`.**
7. **Report** to the user how many pages were created / updated / removed, and flag
   anything you noticed but didn't fully resolve (an `## Open Questions` item, a
   suspected-but-unconfirmed rename, a thin area that could use more coverage).

## Lint workflow

When asked to health-check the wiki instead of update it:

1. Scan for orphan pages (no inbound `[[wikilink]]`), broken wikilinks (link target has
   no file), and pages whose `paths` no longer exist on disk.
2. Scan for pages whose `verified_commit` is far behind current `HEAD` relative to how
   much their `paths` have actually changed since (a stale page whose code hasn't moved
   is fine; a stale page whose code has moved a lot is a problem).
3. Report findings by severity; offer to fix mechanical issues (broken links, dead
   paths) directly.

## Domain reference

This section is a map of where things live as of the last full regeneration — update it
whenever a regeneration finds the package layout has shifted, so the next run starts
oriented instead of rediscovering the same moves. See `codemap.md` for the authoritative,
page-linked version; this is just enough context to brief a focused reader or sub-agent.

- `agent_core/` — the per-turn agent primitives: `turn/`, `hooks/`, `events/`,
  `context/`, `providers/`, `skills/`, `tools/`. This superseded the old `sdk/` package
  (which is now an empty, unimported shell — don't document it as live).
- `agent_runtime/` — session/runner orchestration above a single turn: factory,
  compaction, scratchpad hook, sub-agent spawn.
- `agents/` — `AgentProfile` definitions and `build_agent()`.
- `providers/` (top-level) — provider-adjacent helpers (fakes, vision) distinct from
  `agent_core/providers/`; confirm the split's current shape before documenting it as
  settled.
- `server/` — aiohttp app factory and HTTP routes (`_*_routes.py`), serves `server/ui/`.
- `server/ui/` — React 18 + Vite frontend.
- `tools/` — LLM-callable tool implementations, grouped by category (`browser/`,
  `virtual_computer/`, `memory/`, `integrations/`, `custom_tools/`, `generation/`,
  `desktop/`, `web/`, `scratchpad/`, `misc/`).
- `browser/` (top-level) — the actual browser runtime (profiles, sessions, Playwright
  driving); `tools/browser/` is the LLM-facing tool wrapper around it.
- `skills/` (top-level) — skill storage, policy, and tool-category resolution; distinct
  from `agent_core/skills/`, which loads skills into a running turn.
- `integrations/` — application-level catalog, operations, and grants for tool
  integrations (what an agent is allowed to do).
- `brokering/` — the credential-broker subsystem underneath integrations: broker
  subprocess lifecycle, RPC, catalog validation. Also used for model-provider
  connections, not just tool integrations.
- `conversations/` — conversation persistence (history, events, titles, profiles).
- `tasks/` — the autonomous goal/routine engine.
- `artifacts/`, `custom_apps/`, `packs/` — newer subsystems; confirm scope and maturity
  before writing pages, they may still be thin.
- `config/` — `config.yaml` loading + env-var interpolation → `AppConfig`.
- `models/`, `migrations/`, `setup/`, `utils/`, `container/`, `scripts/` — shared types,
  one-time data migrations, first-run setup wizard, shared utilities, inference
  client/server + accessibility tree, runtime helper scripts.
- `plans/` — proposals and follow-ups, **not** necessarily implemented behavior. Don't
  treat anything here as a source of truth for current code.

## Rules

1. **Every claim traces to code you actually read at the stated commit.** No
   extrapolating from memory of a past version, no copying a claim from the deleted
   pre-refactor wiki without re-verifying it against current source.
2. **Always update `index.md`, `codemap.md`, and `.state.yml` after any run** — a wiki
   whose index drifts from its pages is worse than no index.
3. **Link liberally.** If a page name exists or should exist, make it a `[[wikilink]]`.
4. **Note renames and removals explicitly** rather than silently dropping them — a
   reader with the old name in mind needs the breadcrumb.
5. **Dates are absolute.** `YYYY-MM-DD`, never relative.
6. **Ask before large destructive reorganizations** — collapsing many pages into one,
   deleting a whole category, or similar. Targeted refresh and even full regeneration of
   individual pages doesn't need to ask; wholesale restructuring of the wiki's shape
   does.
7. **Be honest about gaps.** An `## Open Questions` note is better than a confident
   guess.
