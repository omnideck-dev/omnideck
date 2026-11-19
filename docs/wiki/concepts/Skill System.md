---
title: Skill System
type: concept
tags: [skills, tools, agent, profile]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "skills/"
  - "agent_core/skills/"
---

# Skill System

## Overview

A **skill** is a stored, user-editable bundle of a prompt and the tool categories it
grants. Skills are how an `AgentProfile` controls which tools an agent has, and how an
agent can expand its own capabilities mid-conversation via the `load_skill` meta-tool,
without restarting the turn.

The system is split across two packages with a clean storage/runtime boundary:

- **`skills/`** (top-level) — the definition side: `SkillRecord` persistence, policy
  (which categories a skill may grant), resolution (`SkillRecord` → runtime `Skill`),
  and the `load_skill` / `list_available_skills` meta-tools exposed to the LLM.
- **`agent_core/skills/`** — the runtime side: the `Skill` dataclass itself and how a
  loaded skill's tools and prompt get spliced into an in-flight turn (owned by the
  turn/hooks machinery — see [[Turn Lifecycle]] and [[Hooks System]] for that half).

## How It Works

### 1. Storage: `SkillRecord`

`skills/_store.py` defines `SkillRecord` (Pydantic): `id`, `name` (must be unique —
it's the LLM-facing lookup key), `description`, `prompt`, and `tool_categories: list[str]`.
Records are JSON files, one per `id`, under `<home_dir>/skills/`. No live tool
callables are stored — only category IDs.

### 2. Tool categories: the assignable unit

`skills/_tool_categories.py:tool_categories()` returns every `ToolCategory` (id,
label, description, live `tools` list, and `connected` flag for integration-backed
categories) available right now, given current feature flags and integration
connections. A skill grants categories, never individual tools — this keeps skill
records stable even as the tools inside a category change. See [[Tool Architecture]]
for the full category table.

### 3. Resolution: record → runtime `Skill`

`skills/_resolve.py:resolve_skill()` / `resolve_skill_by_name()` take a `SkillRecord`,
look up each granted category via `tool_categories()`, skip any category blocked by
policy (logging a warning), concatenate the surviving categories' tools, and return an
`agent_core.skills.Skill` (id, name, description, prompt, tools).

### 4. Policy: restricted categories and reserved skills

`skills/_policy.py` hard-codes `RESTRICTED_TOOL_CATEGORY_IDS = {"browser"}` — no
user-editable skill may grant the `browser` category; browser access is controlled
separately per agent profile, not through the skill system. `RESERVED_SKILL_IDS =
{"browser"}` marks the legacy `browser` skill id as an application capability rather
than a user-visible skill — `strip_reserved_skills()` filters it out of a profile's
skill list, and `is_reserved_skill_id()` hides it from `list_available_skills()`.

### 5. Loading: the LLM-facing meta-tools

`skills/_tools.py` exposes two tools to the model:

- `list_available_skills()` — lists every non-reserved skill's name and description.
  A skill whose categories currently grant no tools (feature off, integration not
  connected) still appears; it just loads nothing until that changes.
- `load_skill(name)` — resolves the record by name, then calls
  `agent_capabilities.load(skill)` (via `get_active_agent_capabilities()` from
  `agent_core.agent_capabilities`) to splice the skill's tools and prompt into the
  *currently running* turn. Already-loaded skills return instantly without
  duplicating tools. Both calls print a Rich console panel (`_log_skill_loaded`, etc.)
  as a side effect, for operator visibility in the terminal.

### 6. How a profile pre-loads skills

An `AgentProfile`'s `skills: list[str]` field names skill IDs to resolve and load at
turn start, before the first model call — this is how most agents get their "default"
tool set without the model having to call `load_skill` itself. See [[AgentProfile]].

## Where It Lives

| Path | Role |
|------|------|
| `skills/_store.py` | `SkillRecord` model + JSON persistence |
| `skills/_tool_categories.py` | `ToolCategory`, `tool_categories()` |
| `skills/_resolve.py` | Record → runtime `Skill` resolution |
| `skills/_policy.py` | Restricted categories, reserved skill IDs |
| `skills/_tools.py` | `load_skill`, `list_available_skills` meta-tools |
| `agent_core/skills/` | Runtime `Skill` dataclass, in-turn loading mechanics |
| `agent_core/agent_capabilities.py` | `get_active_agent_capabilities()` — the per-turn mutable capability set `load_skill` mutates |

## Key Details

- **A skill's name, not its id, is the LLM-facing key** for `load_skill(name)` —
  `save_skill_record()` rejects a name collision across different ids, so names stay
  unambiguous for the model even though profiles reference skills by id internally.
- **The `browser` tool category is categorically unavailable to user-created skills** —
  this is enforced in `skills/_policy.py`, independent of whatever the UI lets a user
  type into a skill's category list.
- **Resolution is pure and side-effect-free** — `resolve_skill()` doesn't mutate
  anything; `load_skill()` is the one place a skill's tools actually land in a running
  turn, via `agent_capabilities.load()`.
- **Integration categories degrade gracefully** — a skill granting `email` still
  resolves if no email integration is connected; it just carries zero tools until one
  is.

## Open Questions

- The exact mechanics of `agent_capabilities.load()` and how `agent_core/skills/`
  splices a loaded skill's prompt into history belong to [[Turn Lifecycle]] / [[Hooks
  System]] — not independently re-verified from this page's research pass.

## Sources

- None beyond source code.
