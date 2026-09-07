# Skills: current limitations, and the case for adopting the Agent Skills standard

**Status:** Direction-setting document for team discussion. Not an execution plan — no code changes are proposed to land from this document as-is. Companion to `plans/progressive_skill_loading.md` (the original design of the current skill-loading mechanism) and `plans/pack_system.md` §3 (Skill as a packable item kind).

## 1. Motivation

`plans/progressive_skill_loading.md` shipped the mechanism Omnideck uses today: skills as tool+prompt bundles, loaded mid-turn via `load_skill`. That plan explicitly named a tradeoff and accepted it as a risk to live with — "Extra round-trip: `load_skill` costs one LLM iteration before the model can use the loaded tools." That tradeoff, plus a few gaps that were out of scope for that plan, are worth revisiting now for three reasons:

1. Since that plan landed, **Agent Skills** — a format Anthropic originally shipped for Claude and then released as an open, cross-vendor standard — has been adopted by a long list of independent products (Claude Code, Cursor, VS Code Copilot, GitHub Copilot, Gemini CLI, OpenCode, Goose, Letta, ChatGPT/Codex, JetBrains Junie, and dozens more, per [agentskills.io](https://agentskills.io)). A live registry/marketplace (`skills.sh`, `npx skillsadd <owner/repo>`) already exists on top of it.
2. `plans/pack_system.md` is about to design a distribution/packaging format for exactly this item kind. Reinventing a sixth manifest format for "Skill" specifically, at the moment an adopted open standard exists for nothing else, is worth deciding on purpose rather than by default.
3. Two gaps fall out of how discovery works today that are worth naming and designing for regardless of the format question: skills are invisible to the model unless the agent decides to look, and there is no grouping concept above the individual skill.

## 2. Current state — what a skill is today

A skill (`agent_core/skills/_store.py::SkillRecord`) is a flat JSON record: `id`, `name`, `description`, `prompt`, `tool_categories: list[str]`. Stored one file per skill at `{settings.home_dir}/skills/{id}.json` — no directory, no bundled files. `resolve_skill()` expands a record into a live prompt fragment + tool set by resolving each category id through `agent_core/skills/_tool_categories.py`.

Discovery and loading are both LLM tool calls (`agent_core/skills/_tools.py`): `list_available_skills()` returns the catalog, `load_skill(name)` adds that skill's tools to the running `AgentState` and injects its prompt fragment. Critically, **nothing calls these automatically.** A profile's baseline skill set comes from `AgentProfile.skills: list[str]` (`agents/_agent_profiles.py:35`) plus `allow_load_skills: bool = True` (line 37) gating whether the model is even allowed to load more — but whether the model *knows to look* is entirely a function of whether that profile's own system prompt tells it to. The shipped `omnideck` profile does this explicitly (`agents/default_profiles/omnideck.json`: *"Call list_available_skills() to see what skills are available."*) — but that's prompt-engineering discipline per profile, not a guarantee. A profile author who omits that line ships an agent with silently unreachable skills.

## 3. Limitations, concretely

| Limitation | Consequence |
|---|---|
| No bundled files — a skill is prompt text + category references only | A skill can never introduce a new capability, only recombine `tool_categories` that already exist as Python code in the host app. There's no equivalent of a skill shipping its own script or reference doc. |
| Discovery is a manual, profile-prompt-dependent tool call | Skills aren't visible to a model unless its profile explicitly instructs it to call `list_available_skills()` first. This was a named, accepted tradeoff in the original design ("extra round-trip") — but it also means there's no user-initiated path at all, only an agent-initiated one gated by prompt text (§4 below). |
| No portability | Records reference Omnideck-internal `tool_categories` ids and have no folder/manifest shape recognizable outside this codebase. Nothing authored here works elsewhere; nothing authored elsewhere works here. |
| No packaging metadata | No `license`, no `compatibility`/environment-requirement field, no validator equivalent to the spec's `skills-ref`. |
| Flat, ungrouped catalog | `AgentProfile.skills` is a flat list of individual ids — every profile enumerates skills one at a time. There's no reusable named collection the way `tool_categories` already groups individual tools (§5 below). |

## 4. The discovery gap makes `/` commands genuinely valuable

Because loading is entirely agent-initiated and prompt-dependent, there is currently **no deterministic, user-initiated way to load a skill.** A user who already knows exactly which skill they want (they named it, they've used it before) has no way to force it — they can only phrase a request in natural language and hope the active profile's prompt causes the model to check the catalog and pick correctly. There's no existing slash-command precedent in `server/ui/src` today — this would be new UI surface, not an extension of something already there.

**Proposal:** a `/skill-name` (and `/skills` to list) affordance in the chat input that resolves and calls `load_skill(name)` deterministically before the turn starts, bypassing model judgment entirely for the case where the user already knows what they want. This is a complement to `list_available_skills`/`load_skill`, not a replacement — natural-language-triggered discovery still matters when the user doesn't know which skill applies, or wants the agent to reason about it (e.g. combining several).

Worth deciding as a team: whether `/command` resolution happens client-side (parse and dispatch before the message reaches the agent loop at all — recommended, since the entire point is removing the model from the decision) or server-side as a pre-turn injection. The former is more deterministic and doesn't cost an LLM iteration at all, which directly removes the "extra round-trip" cost the original plan flagged as a risk — for the subset of cases where the user, not the model, is doing the choosing.

## 5. Skill categories/groups, referenceable from a profile

Tools already have this pattern — `tool_categories()` groups individual functions into named bundles (`coding`, `browser`, `memory`, etc.) that a skill references collectively rather than tool-by-tool. Skills have no equivalent: a profile that wants five related skills lists five ids, one at a time, and that list has to be hand-maintained per profile.

**Proposal:** a named `SkillCategory` (or reuse whatever vocabulary the team prefers — "group," "tag") — a collection of skill ids, defined independently of any one profile, that a profile can reference wholesale the same way it already resolves `tool_categories` into tools. Concretely: `AgentProfile.skills` gains the ability to reference a category id, not just individual skill ids, and category membership expands at resolve time exactly like `resolve_skill()` already expands categories into tools today.

This is useful independent of anything else in this document, but it also does real work for two things already in flight:

- It's the natural place to reuse the `category` field `plans/pack_system.md` §4 already lists as pack manifest metadata for discovery/browsing — the same vocabulary could describe both.
- If §6 below leads to adopting the spec's automatic stage-1 disclosure (every skill's name+description loaded for free, no tool call needed), categories are what keep that affordable — a profile only needs stage-1 metadata for the categories it actually opted into, not the entire installed skill library.

## 6. The case for adopting the Agent Skills format

A skill in the open standard is a **folder**: `SKILL.md` (YAML frontmatter + Markdown body) plus optional `scripts/`, `references/`, `assets/`. Frontmatter: `name` (≤64 chars, slug, must match folder name), `description` (≤1024 chars, required, states both what and when), optional `license`, `compatibility` (environment requirements), `metadata` (free-form key/value), and an experimental `allowed-tools` (space-separated pre-approval list, e.g. `Bash(git:*) Read`). Loading is three-stage: every skill's name+description loads automatically at startup (~100 tokens each); the full body loads when the model decides it's relevant; bundled files load only as referenced.

What adopting this buys, concretely:

- **Ecosystem, for free.** A skill authored for Claude Code, Cursor, OpenCode, Goose, or any of the other adopters works in Omnideck with no rewrite, and vice versa. Users switching to or alongside Omnideck bring what they already have.
- **Distribution, for free.** `skills.sh` (`npx skillsadd owner/repo`) already exists as a git-backed registry with install-count ranking. This is materially the same shape `plans/pack_system.md` Phase E ("git-backed packs... reopens the versioning/check-for-updates work, now with git as the concrete transport") and Phase H ("community library... needs its own design pass, real team bandwidth") are planning to build from scratch — for the Skill item-kind specifically, it already exists and is live.
- **A head start on the security scanning gate.** `plans/pack_system.md` §9 requires a deterministic scan on every pack import/update. `allowed-tools` and `compatibility` give a structured starting point for what that scanner checks for skills specifically, rather than designing the schema from nothing. The spec's own `skills-ref validate` is a concrete precedent for what an import-time validator looks like.
- **Bundled files solve the "skills can't add new capability" limitation** in §3 — a skill could ship a script that becomes a custom-tool-like capability, rather than being limited to recombining pre-existing `tool_categories`.

What doesn't map cleanly, and needs a real design decision rather than a silent rewrite:

- **`tool_categories` vs `allowed-tools`** are different granularities — categories are host-defined bundles of many functions, `allowed-tools` is a flat per-tool allowlist. Adopting the spec doesn't remove the need for something like categories (§5 still stands on its own); it means deciding how category membership is expressed within or alongside `allowed-tools`/`metadata` rather than as a separate proprietary field.
- **Bundled files need a physical home.** Today a skill is one JSON file with nowhere to put a script. This is the same problem `plans/pack_system.md` §5 (on-disk layout, `~/.packs/<vendor>/<name>/<type>/`) is already solving for other item kinds — skill adoption converges with that work rather than duplicating it.
- **Automatic stage-1 disclosure vs. today's fully-manual gate** is a real behavioral choice, not just a format choice — see open questions below.

## 7. Recommendation

- Treat the Skill item-kind in `plans/pack_system.md` as a candidate for `SKILL.md`-based storage rather than a bespoke sixth format — this doesn't block that RFC's other four item kinds (Profile, Tool, App, Routine), which still need their own design since no external standard covers them.
- Land skill categories (§5) as an Omnideck-native improvement independent of the format decision — it's useful either way and has no external dependency.
- Land `/command` deterministic skill loading (§4) independent of the format decision too — it's a UI/discovery fix, not a storage fix.

## 8. Open questions for the dev team

- Does adopting `SKILL.md` mean today's flat `{home_dir}/skills/{id}.json` records become folders on disk — and does that migration fold into `plans/pack_system.md` Phase B's already-planned storage migration, or ship as a smaller change ahead of it?
- Should the spec's automatic stage-1 disclosure (every skill name+description always in context) replace today's fully-manual `list_available_skills()` gate, or should Omnideck deliberately keep discovery opt-in per profile (the existing `allow_load_skills` flag) for context-budget reasons on smaller/local models? If categories (§5) exist, should stage-1 disclosure scope to only a profile's assigned categories rather than the entire installed library?
- Where do skill categories live relative to `tool_categories` — a parallel registry, or a single unified "categories" concept spanning both?
- `/command` resolution: client-side dispatch (no LLM round-trip) or server-side pre-turn injection?
- The spec has no built-in version field beyond the free-form `metadata` map — does `plans/pack_system.md` §6's locked/editable model need its own version discipline layered on top for skills specifically?
