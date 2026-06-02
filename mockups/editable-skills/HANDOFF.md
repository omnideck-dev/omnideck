# Handoff — Editable Skills & Tool Bundles (v1)

Status: **design/mockup phase complete, no app code written yet.** This branch
(`claude/editable-skills-tool-bundles-0wy94`) contains design artifacts only.
Read this before implementing.

---

## 1. Goal (v1 scope)

Let users **write and edit skills** in the UI instead of skills being
uneditable Python files. A skill = a prompt fragment ("skill text") + an
optional set of **tool bundles** it grants. Introduce **tool bundles** =
app-defined, curated groups of related tools. v1: users can only **add
bundles** to a skill (no per-tool picking, no user-defined bundles).

---

## 2. Decisions locked in (with rationale)

- **No overrides.** Built-in skills are **starters**: seeded once into an
  editable store, then they're just normal editable records — edit one and the
  change persists in place. No "default underneath," no reset-to-default.
  *(We explicitly dropped an earlier override model at the user's request.)*

- **Three tiers of tools** — only the middle one is skill-assignable:
  1. **Core tools** — always on for every agent (`get_core_tools()` in
     `sdk/tools/_core.py`). Not assignable. Includes scratchpad, `load_skill`,
     `spawn_agent`, `send_file`, `describe_image`, etc. **Note: scratchpad is
     core, so it is NOT a bundle.**
  2. **Tool bundles** — code-defined, curated lists a skill grants. *Not* 1:1
     with packages — grouping is a curation decision (e.g. `memory` =
     `remember`/`forget`/`load_memory` as its own bundle).
  3. **Integration tools** (`email`/`calendar`/`drive`/`contacts`/`http`) —
     auto-included when an integration is connected + permissioned (gated by
     `_ids_with_access` in `sdk/tools/_core.py`). **Governed by the
     Integrations tab, NOT assigned via skills.**

- **UI placement:** a new **"Skills"** tab in the Settings page
  (`server/ui/src/components/SettingsPage.jsx` `ALL_TABS`), placed right after
  "Agent Profiles" (profiles already reference skills by name).

- **Sub-navigation:** the new **Library Header** pattern, codified as **§27 in
  the SIGNAL design language** (`docs/design/design_language.html`). View tabs
  on the LEFT drive the view (`My Skills` master-detail editor ·
  `Tool Bundles` read-only catalog), scoped search on the RIGHT. Classes:
  `.dl-libhead`, `.dl-libhead-views`, `.dl-view-tab`, `.dl-view-count`,
  `.dl-libhead-search`. It is intentionally distinct from the §14 brand tabs
  (body font, mixed-case, count badge) so a secondary switch doesn't compete
  with the uppercase Settings tabs.

- **Bundle-assignment UI:** reuse the existing green **chip-toggle** pattern
  from `ProfileBuilder` (`.chip`/`.chipActive` with a ✓) — a skill granting
  bundles should read identically to a profile granting skills.

---

## 3. Key codebase facts (the map)

**Skill model & registry** — `sdk/skills/_registry.py`
- `Skill(BaseModel)`: `name`, `description`, `prompt`, `tools: list[Any]`.
- `tools` currently holds **actual callables**. `_SKILL_REGISTRY` is in-memory;
  built-ins registered lazily in `_ensure_builtins()`.

**Built-in skill definitions** — `skills/*.py`
(`coder`, `browser`, `goal_planner`, `desktop`, `image_generation`,
`music_generation`). Each builds a `Skill(...)` with a `tools=[...]` list.

**Runtime composition** — `sdk/skills/agent_state.py` (`AgentState`,
dedup by `__name__`), `sdk/skills/_tools.py` (`load_skill`,
`list_available_skills`), `sdk/hooks/_loaded_skill_hook.py` (rebuilds the
system-prompt skill section).

**Profiles reference skills by name** — `agents/_agent_profiles.py`
(`AgentProfile.skills: list[str]`); HTTP CRUD in `server/_profile_routes.py`;
profiles persist as JSON under `~/.computron_9000/agent_profiles/`.

**Turn wiring** — `server/message_handler.py`: builds
`AgentState(await get_core_tools() + active_agent.tools)`, preloads profile
skills, restores per-conversation loaded skills, persists them
(`conversations/_store.py` `save/load_loaded_skills`). The default agent is
built with `tools=[run_bash_cmd, remember, forget]` (memory tools currently
come in here, not from a skill — relevant to the `memory` bundle).

**Tool packages** (bundle source material) — `tools/{virtual_computer,
browser, web, memory, scratchpad, generation, desktop, misc, integrations}`.
Public exports are in each package's `__init__.py __all__`.

**UI** — `server/ui/src/components/SettingsPage.jsx` (tab registry),
`ProfilesTab.jsx` + `ProfileList.jsx`(+`.module.css`) + `ProfileBuilder.jsx`
(+`.module.css`) are the master-detail pattern to mirror. Design tokens:
`server/ui/src/global.css`. Primitives: `components/primitives/`. Feature flags
via `contexts/AppData.jsx` (`features.*`). Icons: Bootstrap Icons (`bi bi-*`).

---

## 4. ⚠️ The central implementation problem

`Skill.tools` holds **live callables**, but editable skills loaded from JSON
**cannot store callables**. So:

- Persisted/editable skills must store **bundle IDs** (`bundles: list[str]`),
  not tools.
- Add a **bundle registry in code**: `bundle_id -> (name, description, list of
  tool callables)`, grouped from the `tools/*` packages. This is the new
  source of truth for "what tools does bundle X grant."
- The skill **loader** resolves `skill.bundles -> tools` via the bundle
  registry at load time (respecting feature flags / grounding-tool stripping
  the way `_ensure_builtins` does today).
- Built-in starters get **seeded** into the editable store on first run by
  translating their current `tools=[...]` into the equivalent `bundles=[...]`.
- Skill **names are the stable key** profiles use (`AgentProfile.skills`) — keep
  names stable across edits, or handle renames.

---

## 5. Suggested implementation plan

**Backend**
1. `bundles` registry module (code-defined): id, label, description, icon,
   optional feature gate, `tools: list[Callable]`. Group from `tools/*`.
2. Persistent skill store (JSON under `~/.computron_9000/skills/`, mirroring
   profiles): fields `name`, `description`, `prompt`, `bundles: list[str]`,
   `enabled`. Seed built-in starters on first run.
3. Update `Skill`/loader so `tools` is derived from `bundles` via the registry
   (keep `get_skill`/`list_skills` working; integrate feature gating).
4. `/api/skills` routes (GET list, GET one, POST create, PUT update, DELETE) —
   model on `server/_profile_routes.py`.

**Frontend**
5. `LibraryHeader` primitive (`components/primitives/LibraryHeader.jsx` +
   `.module.css`) implementing §27 (view tabs + scoped search).
6. `SkillsTab.jsx` registered in `SettingsPage` `ALL_TABS` after `profiles`:
   - `My Skills`: `ProfileList`-style list + `ProfileBuilder`-style editor
     (name, description, enabled, skill-text textarea, bundle chip-toggles).
   - `Tool Bundles`: read-only catalog grouped by tier (core/bundle/
     integration) with tool counts; **no `+ New`** (read-only in v1).
   - Per-view scoped search.
7. Point `ProfileBuilder`'s skill chips at the new `/api/skills` list.

---

## 6. Open questions for the user

- Confirm storage = JSON under `~/.computron_9000/skills/` + first-run seeding.
- Integration tools stay global-when-connected (not skill-scoped) in v1 —
  confirm.
- Hierarchy stays: profile → skills → bundles (profiles don't assign bundles
  directly). Confirm.
- Deleting a seeded starter: allowed (it's just a record now) or soft-disable
  only?

---

## 7. Artifacts in this branch

- `mockups/editable-skills/index.html` — interactive mockup (open in a browser:
  skills editor + 3-tier bundle catalog + chip toggles). **Note:** its sub-nav
  still uses the older segmented pill; fold in the §27 inverted Library Header
  (see `subnav-G-*.png`) when building.
- `mockups/editable-skills/subnav-*.png` — sub-nav option explorations.
  `subnav-G-inverted-*.png` is the chosen direction.
- `docs/design/design_language.html` — **§27 Library Header** (new section +
  CSS); Iconography renumbered to §28.

No application code has been changed yet.
