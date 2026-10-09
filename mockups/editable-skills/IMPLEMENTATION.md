# Implementation Design — Editable Skills & Categories (v1)

## Context

Today skills are hard-coded Python (`skills/*.py`), each a `Skill(name, description,
prompt, tools)` holding **live tool callables**. Users can't create or edit them, and
tool access is decided in code: integration tools are injected globally for every agent,
`spawn_agent`/`load_skill` are always on, and `remember`/`forget` are hand-wired onto the
interactive agent only.

We're moving to a user-editable model. A **skill** = prompt text + a set of **categories**.
A **category** = an app-defined group of tools, with one category tagged per tool in code.
A **profile** = model + system prompt + attached skills + two autonomy toggles. Built-in
skills become editable starter records seeded on first run. The UX is locked in
`mockups/editable-skills/index.html`.

## Target model

```
Profile ──has──> Skills ──grant──> Categories ──contain──> Tools
  │                                                          ▲
  ├─ allow_spawn  ─────────────── gates spawn_agent ─────────┤ (always-on base tools:
  └─ allow_load_skills ────────── gates load_skill ──────────┘  scratchpad, send_file,
                                                                play_audio, describe_image,
                                                                datetime — invisible, never
                                                                category-assignable)
```

Two real tiers of tools:
- **Base tools** — always on for every agent, not configurable, not shown in the UI.
  `spawn_agent`(+`list_agent_profiles`) and `load_skill`(+`list_available_skills`) are base
  tools **conditionally included** by the profile's two toggles.
- **Categories** — the assignable unit. Each tool is tagged with exactly one category.
  - *Standard* categories: `coding`, `browser`, `webfetch`, `memory`, `planning`,
    `image_generation`, `music_generation`, `desktop`. Feature-gated ones disappear when
    their feature flag is off.
  - *Integration* categories, keyed by **capability** (not provider): `email`, `calendar`,
    `drive`, `contacts`, `http`. Always listed; resolve to **zero tools** unless a
    permissioned integration provides that capability. A skill may grant them anytime.

## Key architecture decisions

### 1. Per-tool category membership + a coverage test (the maintainability guarantee)
A category registry module (`agent_core/tools/_categories.py`) defines each category and a **lazy
loader** that imports and returns its tools — mirroring how `agent_core/tools/_core.py` and
`_ensure_builtins` already lazy-import to keep startup fast and respect feature/heavy-dep
gating. Membership is the source of truth for "what tools does category X grant."

The "you can't forget to categorize a new tool" property is enforced by a **test**, not a
decorator-scan (a scan would force eager import of playwright/torch/etc.). The test asserts
every public tool exported from `tools/*/__all__` belongs to exactly one category **or** the
base set — fail = a new tool was added without a category.

### 2. Stored record vs resolved skill
- **`SkillRecord`** (persisted JSON, one file per `id`): `{ id, name, description, prompt,
  categories: list[str], enabled, builtin }`. `id` is a stable hidden key (the foreign key
  used everywhere); `name` is an editable, unique display field. No callables — kills the
  `list[Any]` pydantic deadlock that motivated lazy registration (`agent_core/skills/_registry.py:23`).
- **Resolved skill** (runtime): the existing `Skill` object with `.tools` populated, built at
  composition time. `AgentState.add()` is unchanged.

### 3. Async resolution end-to-end
`get_skill(name)` (sync) → `resolve_skill(skill_id)` (async), because integration categories need
`await registered_integrations()`. **Every one of the three composition sites is already
inside an async function that already awaits `get_core_tools()`**, so this is free. The
loaded-skill hook never resolves categories (it only reads prompts off already-added skills),
so it's untouched.

### 4. Integration categories reuse the existing `_core.py` wiring
Extract the per-capability `_ids_with_access` + `build_*_tool(ids)` blocks
(`agent_core/tools/_core.py:54-130`) into a shared `integration_tools_for(capability, records)`.
Both the (now-shrunk) `get_core_tools` *removal* and the integration-category resolver call
it — single source of truth for the access thresholds and factory wiring. Disconnected
capability → returns `[]` → granting that category is harmless. Catalog visibility uses the
same `_ids_with_access(records, cap, READ)` non-empty check to render the connected dot.

### 5. Profile autonomy toggles
`AgentProfile` gains `allow_spawn: bool = True` and `allow_load_skills: bool = True`. At
composition, the base set includes `spawn_agent`/`list_agent_profiles` iff `allow_spawn`, and
`load_skill`/`list_available_skills` iff `allow_load_skills`.

### 6. Loaded-skill persistence format is unchanged
Conversation metadata stores a list of skill **ids** (`conversations/_store.py:123` — formerly
"names"; identical values for built-ins, so existing metadata still resolves). Restore
re-resolves by id via async `resolve_skill`. Restore is independent of `allow_load_skills`
(already-loaded skills are honored; the toggle only governs whether the agent can load *more*).

### 7. Stable hidden `id`; `name` is editable (mirrors how profiles split id/name)
`profile.skills` and `metadata.loaded_skills` reference skills by stable **`id`**, not name, so
a skill can be freely renamed without breaking references. Built-in starters seed with `id`
equal to their current canonical slug (`coder`, `browser`, `goal_planner`, `image_generation`,
`music_generation`, `desktop`, plus the new `assistant`) — exactly what existing
profiles/conversations already store — so **no reference migration is needed**. `name` must
stay **unique** so the LLM-facing `load_skill(name)`/`list_available_skills` are unambiguous
(resolved to `id` internally). `AgentState` dedups by `id`. Unknown-skill handling is made
**consistent**: skip-with-warning everywhere (today the task executor *raises* —
`tasks/_executor.py:100`).

## The three composition sites (all change identically)

| Site | Current | Change |
|---|---|---|
| `server/message_handler.py:268-288` | `get_core_tools() + active_agent.tools`; loop `get_skill` (skip on None); restore loop | base set gated by toggles; `await resolve_skill`; drop the hard-wired `remember/forget/run_bash_cmd` from `_build_agent_from_profile:242` (now via categories) |
| `tasks/_executor.py:67,96-102` | `get_core_tools()`; loop `get_skill` (**raises** on None) | gated base set; `await resolve_skill`; **skip-with-warning** not raise |
| `agent_core/tools/_spawn_agent.py:157-168` | `get_core_tools()`; loop `get_skill` (returns error string on None) | gated base set; `await resolve_skill` |

A shared helper `compose_agent_tools(profile, extra_tools=()) -> list[Callable]` (async)
centralizes: gated base set + resolved skill categories + dedup. All three sites call it.

## Behavior changes to guard (regressions)

1. **Integration tools no longer global.** Mitigated by seeding an `assistant` starter skill
   granting all integration categories + `memory`, and granting it to the `omnideck` default
   profile in the migration (only if `skills == []`, so user edits aren't clobbered).
2. **`remember`/`forget` were interactive-only and hard-wired.** They move into the `memory`
   category; the seeded `assistant` skill carries them so the default agent keeps them.
3. **`spawn_agent`/`load_skill` were always on.** Now toggle-gated; seeded profiles default
   both to true so nothing regresses.
4. **`run_bash_cmd` was hard-wired on the interactive agent** outside any skill. It belongs to
   the `coding` category now; the seeded `omnideck` profile gets the `coder` skill.
5. **ProfilesTab hardcodes `availableSkills`** (`ProfilesTab.jsx:24`) and lists the *wrong*
   names (`image_gen`/`music_gen` vs registered `image_generation`/`music_generation`) — fix
   by fetching `/api/skills`.

## Migration

No **data migration** is required — skills were hard-coded, so nothing skill-shaped exists on
disk to transform. Two mechanisms cover the transition:
- **First-run seed** (`_006`): writes the starter `SkillRecord`s and grants the default trio
  to `omnideck` only if its `skills` is still empty. A seed, not a transform; a deleted starter
  stays deleted (the migration is marked applied).
- **References survive untouched.** `profile.skills` and `metadata.loaded_skills` already hold
  the built-in slugs (`coder`, `browser`, …); because seeded `id`s equal those slugs, every
  existing reference resolves with no rewrite. New `AgentProfile` toggle fields default via
  pydantic, so old profile JSON loads as-is.

## Backend modules

- **New** `agent_core/tools/_categories.py` — `Category` defs, lazy loaders, `list_categories(features)`,
  `resolve_category_tools(...)`, `catalog(records, features)` (for the API, with connection state).
- **New** `agent_core/tools/_integration_tools.py` — `integration_tools_for(capability, records)` +
  `_ids_with_access` (moved from `_core.py`).
- **New** `agent_core/skills/_store.py` — `SkillRecord` (`id`+unique `name`), `list/get/save/
  delete_skill_record`, JSON `{id}.json` under `{home}/skills/`; mirrors `agents/_agent_profiles.py`.
- **New** `agent_core/skills/_resolve.py` — async `resolve_skill(name)`, `resolve_skill_tools(category_ids)`,
  `compose_agent_tools(profile, extra_tools=())`.
- **Change** `agent_core/tools/_core.py` — drop integration blocks; add `datetime_tool` to base; expose
  the toggle-gated base assembly.
- **Change** `agents/_agent_profiles.py` — add `allow_spawn`, `allow_load_skills`.
- **Change** the 3 composition sites to call `compose_agent_tools`.
- **New** `migrations/_006_install_default_skills.py` — seed 6 starters + `assistant`; grant
  `assistant`+`coder`+`browser` to `omnideck` if empty. Register in `migrations/_runner.py`.
- **Retire** (last step) `_ensure_builtins`/`_SKILL_REGISTRY` once the store is source of truth.

## API

- `server/_skill_routes.py` (mirror `_profile_routes.py`): `GET/POST /api/skills`,
  `GET/PUT/DELETE /api/skills/{id}`. POST/PUT enforce a unique `name`; rename is allowed (id is
  stable). DELETE allowed for any record (starters included).
- `server/_category_routes.py`: `GET /api/categories` → catalog with per-category
  `{id, label, description, icon, kind, tool_count, connected?}`; integration categories carry
  live connection state.
- Register both in `server/aiohttp_app.py`.

## Frontend

- **New** `components/primitives/LibraryHeader.jsx` (+`.module.css`) — §27: view tabs (left,
  body font, count badge) + scoped search (right).
- **New** `components/SkillsTab.jsx` — Library Header switching **My Skills** (master-detail:
  `SkillList` + `SkillBuilder`, mirroring `ProfileList`/`ProfileBuilder`) and **Categories**
  (read-only `CategoryCatalog` — expandable cards, connection-state tag). Register in
  `SettingsView.jsx ALL_TABS` after `profiles`.
- `SkillBuilder.jsx` — name, enabled, skill-text, category chips (bs icon + tool count +
  connection **dot** on integration chips, success/warning tokens).
- **Change** `ProfileBuilder.jsx` — point skill chips at `/api/skills`; add an **Autonomy**
  section with the two toggles.

---

## TDD Roadmap

Each step: **write the failing test first**, then implement to green. Backend first (the UI
depends on the API). Tests live under `tests/` mirroring source; UI under Vitest.

### Backend

1. **Category registry (std).** Test: `list_categories(features)` returns the std set; a
   feature-off flag drops `desktop`/`image_generation`/`music_generation`; grounding-off
   strips `browser_visual_action`/`perform_visual_action`. Impl: `_categories.py` std loaders.
2. **Tool-coverage guarantee.** Test: every callable in each `tools/*/__all__` is in exactly
   one category or the base set (fails on an uncategorized new tool). Impl: adjust membership
   until green — this test is permanent.
3. **Integration tool helper.** Test (mock `registered_integrations`): `integration_tools_for`
   returns read tools at READ, adds write tools at READ_WRITE, `[]` when absent. Impl: extract
   from `_core.py`.
4. **Integration categories + catalog.** Test: integration category resolves via the helper;
   `catalog()` reports `connected` per capability and `tool_count` 0 when disconnected. Impl:
   integration entries in `_categories.py`.
5. **Slim `get_core_tools`.** Test: returns base tools incl. `datetime_tool`, **no** integration
   tools; toggle-gated assembly includes/excludes spawn & load per flags. Impl: edit `_core.py`.
6. **Skill store.** Test: save/get/list/delete `SkillRecord` JSON round-trip keyed by `id`
   (`{id}.json`); duplicate `name` rejected; bad files skipped. Impl: `_store.py`.
7. **Resolution.** Test (mocked registry/integrations): `resolve_skill(id)` builds prompt +
   tools from categories; unknown id → None; feature-off category contributes nothing;
   renaming a record keeps the same `id` so a `profile.skills` reference still resolves;
   `compose_agent_tools` dedups and honors toggles. Impl: `_resolve.py`.
8. **Seeding migration.** Test: migration creates 6 starter records + `assistant` with `id`s
   equal to the canonical slugs; grants the default trio to `omnideck` only when `skills==[]`;
   an existing profile referencing `coder` resolves post-seed (no rewrite); idempotent; a
   deleted starter stays deleted. Impl: `_006_*` + register.
9. **Profile toggles + composition wiring.** Test: `AgentProfile` defaults both toggles true;
   each of the 3 sites composes the same tool set and skips unknown skills with a warning (no
   raise). Impl: model field + route 3 sites through `compose_agent_tools`.
10. **Skill API.** Integration test: CRUD over `/api/skills` keyed by `id`; rename via PUT
    succeeds and keeps `id`; duplicate `name` is rejected; DELETE works on a starter. Impl:
    `_skill_routes.py` + register.
11. **Category API.** Integration test: `/api/categories` returns the gated catalog with
    connection state. Impl: `_category_routes.py` + register.

### Frontend

12. **LibraryHeader.** Vitest: renders both view tabs with counts, switches active view,
    swaps search placeholder. Impl: primitive.
13. **SkillsTab.** Vitest: list renders from mocked `/api/skills`; selecting opens the editor;
    toggling a category chip marks it active; integration chip shows the connection dot;
    Categories view lists categories and expands to tools. Impl: `SkillsTab`/`SkillBuilder`/
    `CategoryCatalog`; register tab.
14. **ProfileBuilder.** Vitest: skill chips come from mocked `/api/skills` (regression: no
    `image_gen`); autonomy toggles render and serialize into the saved profile. Impl: changes.

### Integration / cleanup

15. **End-to-end resolution.** Integration test: a profile with a skill granting `email` gets
    the email tools only when the capability is permissioned; with it disconnected, none —
    and base tools are always present, spawn/load follow the toggles.
16. **Retire the old path.** Remove `_ensure_builtins`/`_SKILL_REGISTRY` and the `skills/*.py`
    registration once the store is the source of truth (the seed migration supplies the same
    content). Keep the prompt text by moving it into the seeded records.

## Verification

- `just unit` after each backend step; `just test-ui` for 12–14.
- `just integration` for 10, 11, 15 against a running container.
- Manual: `just dev`, open Settings → **Skills**, create a skill granting `email`, attach it
  to a profile, connect Gmail, confirm in chat the agent can list mail; toggle off "Allow
  spawning agents" and confirm `spawn_agent` is gone.
