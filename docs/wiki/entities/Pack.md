---
title: Pack
type: entity
tags: [packs, agent-profiles, skills, export, import]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "packs/"
---

# Pack

## Overview

A `Pack` is a portable JSON document for exporting/importing agent profiles and skills
— between installs, or to hand a configured agent to someone else. It's a shim over the
on-disk `AgentProfile`/`SkillRecord` data, never the records themselves: packed forms
never carry a stored id (meaningless on another install) and a packed profile embeds
its skills inline rather than referencing them by id, so a pack can only ever point at
a skill it actually contains.

## Location

`packs/_pack.py`.

## Details

| Model | Role |
|-------|------|
| `PackedSkill` | A skill's shareable content: `name`, `description`, `prompt`, `tool_categories`. No id. |
| `PackedProfile` | A profile's shareable content plus its skills *inline* (see Overview). Excludes local security policy — `id` and `browser_profile_id` never travel. |
| `Pack` | The envelope: `kind` (`"omnideck.pack"`), `version`, `profiles: list[PackedProfile]`, `skills: list[PackedSkill]` (bare skills with no profile). |
| `ImportSummary` | What an import actually created, after fresh id assignment and name de-duplication. |

Export options, both independent:

- **`include_skills`** — when `False`, the profile exports with no skills at all rather
  than dangling references; a skill that no longer resolves, or that's reserved /
  grants a restricted tool category, is silently omitted with a warning rather than
  failing the export.
- **`include_model`** — when `False`, provider/model and the sampling/reasoning fields
  tuned to them (`temperature`, `top_k`, `top_p`, `repeat_penalty`, `num_predict`,
  `think`, `reasoning_effort`, `reasoning_summary`, `thinking_budget`,
  `context_window`) are cleared, so the pack imports cleanly on an install with a
  different model setup. The system prompt and skills are always kept regardless.

Import (`import_pack`) is **always additive**: everything lands with a freshly
generated id, so importing can never clobber an existing profile or skill. All bundled
skills are validated up front (none may grant a restricted tool category) before
anything is written, so one invalid skill can't leave a partial import behind. A
colliding skill or profile name gets a `(imported)` / `(imported N)` suffix rather than
overwriting the existing one.

## Key Functions

- `build_profile_pack(profile_id, *, include_skills, include_model)` — pack one profile
- `build_skill_pack(skill_id)` — pack one bare skill
- `import_pack(pack)` — persist a pack's contents as fresh records; raises on unknown `kind`, a newer `version` than this install supports, or an empty pack

## Related Entities

- [[AgentProfile]] — what gets packed
- [[Tool Architecture]] — skills and tool categories referenced by a pack

## Sources

- None beyond `packs/_pack.py`.
