# Omnideck Pack System — architecture direction (RFC)

**Status:** Direction-setting document for team discussion. Not an execution plan — no code changes are proposed to land from this document as-is.

## 1. Motivation

Omnideck already lets a user hand-export a single agent profile or skill to another install. The ambition is bigger: a **single, standardized way to package and move any functional primitive** — agent profiles, skills, custom tools, custom apps, and routines — as one item or as a curated collection, so that:

- A user can back up or share one thing (a skill, a tool).
- An organization can define a **preset working state** — "every new Omnideck install for this team starts with these agent profiles, these tools, these routines already configured" — the way Ansible provisions a machine to a known state, rather than each teammate hand-configuring their own install.
- Eventually, packs can be **discovered, rated, and installed from a community library**, and published/updated **as git repositories**, not just ad-hoc file downloads.
- None of this should let a user (or the agent, acting on the user's behalf) accidentally break something they installed from a trusted source — installed packs are locked by default.

This is a large, cross-cutting initiative. This document exists to align on shape and sequencing before any of it is scheduled as real work.

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Item** | One functional primitive: an agent **profile**, a **skill**, a custom **tool**, a custom **app**, or a **routine** (a scheduled/recurring task template — this already exists today as `Routine`/`Task` in `tasks/_models.py`; packing it means bundling a `Routine` with its associated `Task`s). |
| **Pack** | The one distributable unit — a manifest plus zero or more embedded files, containing one or more items. Single item or many, same format. Kept as the term (per earlier discussion): it's not user-visible copy today, and it already matches the "Library" vocabulary used in the Skills UI. |
| **Bundle** | Not a different file format — a **pack whose purpose is establishing a working install state** (an org preset, a team preset, a personal "my setup" export), as opposed to a pack shared to hand over one thing. This mirrors the plugin/bundle split from other ecosystems (e.g. OpenCode) without introducing a second container format: a bundle is just a pack with multiple items and a declared intent. Worth confirming this framing with the team rather than inventing a second manifest shape. |
| **Vendor** | The publishing namespace a pack was authored under (an org, a team, a community author, or `custom` for the user's own unpublished items). Defaults to the local user/`custom` for anything built on-device — see §11 on why this sidesteps collision for now. |
| **Locked / editable** | Per-item (and per-pack) flag: whether the agent or user can modify it in place, versus needing to clone it into their own custom space first. |

## 3. Item kinds in scope

Profile, Skill, Tool, App, **Routine** (new addition per this discussion — a `Routine` + its `Task`s, so "check for updates" or any other scheduled workflow becomes packable and shareable the same way a skill is).

## 4. Manifest metadata (discovery & UX)

These fields exist purely to make a pack presentable and searchable — in the near-term UI (§8) and the eventual community library (§9) alike. They live on the **pack** manifest (the discoverable/shareable unit), not on individual items inside it:

| Field | Required | Type | Notes |
|---|---|---|---|
| `title` | Yes | string | Display name of the pack. |
| `author` / `vendor` | Yes | string | Defaults to the local user for anything built on-device (see §2, §11). |
| `short_description` | Yes | plain text | Card/list-view summary. |
| `long_description` | No | markdown | Full detail view. |
| `category` | No | string | For browse/filter grouping once there's enough volume to need it. |
| `images` | No | array | First entry is the card thumbnail; remaining entries populate a detail-view carousel. |

## 5. On-disk layout

Today, storage is scattered: profiles and skills live under the app server's `home_dir` as one JSON file per record; custom tools split a `registry.json` (app `home_dir`) from script files (the *container-mounted* `virtual_computer.home_dir`); apps are bare directories under the container's `apps/`; routines/tasks have their own file store. Standardizing packs means standardizing this too.

Proposed layout, resolving the "grouped by pack vs. grouped by type" tension by nesting type folders **inside** each pack's own folder:

```
~/.packs/
  <vendor>/
    <pack-name>/
      manifest.json          # pack metadata — at the folder root, not a symlink elsewhere
      profile/
      skill/
      tool/
      app/
      routine/
  custom/
    profile/
    skill/
    tool/
    app/
    routine/
```

- `manifest.json` lives at the pack folder's root. Discovery is by **crawling the tree** for `~/.packs/*/*/manifest.json` rather than maintaining a central symlinked index — simpler, and it means a pack folder can just *be* a git working tree with nothing extra bolted on.
- `custom/` holds anything the user (or the agent, on the user's behalf) created directly — flat, no vendor/name nesting, because it isn't "a pack" someone published.
- Open question for the team: which "home" this root actually lives under, since today's storage already straddles two roots (app-server `home_dir` vs. container-mounted `virtual_computer.home_dir`) — tools/apps/routines likely need the container-mounted one for execution access, which argues for `~/.packs/` living there rather than being newly split again.

**Migration.** Landing this layout means moving every existing on-disk profile, skill, tool, and app into it — today's users, however few, already have real data in the old locations. The install base is small right now (no community yet), so the blast radius is limited, but a broken or lossy migration on someone's existing install is still a real, user-visible failure, not a cosmetic one. This needs a concrete, reviewed migration path from the dev team before Phase B ships (see §12) — not an afterthought bolted onto the storage change. Worth checking whether the existing `migrations/` runner (already used for schema changes like `migrations/_013_goals_to_routines.py`) is the right vehicle.

## 6. Read-only enforcement and "clone to customize"

- Installed pack items are **locked by default** (`editable: false`). Enforcement is filesystem-level (read-only permissions on the pack's directory tree), not just a disabled button in the UI — the agent's own tool-execution path and a user poking at files directly should both be physically unable to mutate a locked pack.
- The only path that's allowed to write a locked pack (installing it fresh, or applying an update) should go through an **isolated, elevated-trust component**, not the same process that executes LLM-invoked tools. Omnideck already has a precedent for this shape — `integrations/brokers/*` are separate sandboxed processes holding capabilities the main agent path doesn't have, invoked over a UDS RPC (`integrations/broker_client`). The pack installer/updater should follow that same separation-of-privilege pattern; whether it *reuses* broker infrastructure or is its own analogous component is a design question for the team, not decided here.
- **"Uncloneable" is a courtesy flag, not real protection.** A manifest can optionally mark a pack as discouraging clone-to-customize, and the UI should honor it (hide/disable the affordance). The document should be explicit, and any implementation should be explicit to users, that this is friction against accidental copying — not DRM. A determined user with filesystem access can always route around it, and the design must not oversell otherwise.
- "Clone to customize" copies (not moves) a locked pack's item(s) into `~/.packs/custom/<type>/`, flips `editable: true`, and keeps `source.publisher` for attribution.

## 7. Building a pack: selection and dependency discovery

Packs need an authoring path, not just an installing one:

- **Manual builder**: a "Create Pack" flow (Settings UI, §10) where the user finds/selects items from their own library — including cloneable items embedded from other installed packs, not just their own custom items — fills in the manifest fields from §4, and gets back a pack. An item copied in from another pack keeps its own original `source`/attribution even though it now also lives inside the new one; only items marked cloneable (not `uncloneable`, §6) can be embedded this way.
- **Agent-assisted builder**: the same flow, but the LLM does the selection given an instruction like "package up my email-triage routine so I can share it" — this needs a tool surface that can enumerate candidate items and their references, not just a UI.
- **Dependency discovery is the hard part underneath both.** A Routine references Tasks, a Task references an `agent_profile`, a profile references `skills`, a skill references `tool_categories` — some of this chain is explicit and structural today. Some of it isn't: a skill's free-text prompt or a task's instruction can reference a custom tool by name with no structural link at all, which is exactly the "routine runs a skill that needs a tool that uses a script" case raised in this discussion. Closing that gap reliably may require making those references explicit in the models themselves (a real design decision, not just a packaging concern), rather than assuming it can always be inferred after the fact.
- As a pragmatic complement to best-effort static resolution at build time: an **import-time dependency check** that verifies a routine's referenced profile/skills/tools actually resolved after import, and clearly reports what's missing rather than silently degrading.

## 8. Import / export surfaces

The same underlying pack format should be movable through several different triggers over time. Not all of these are being built now — this table is here so the transport design doesn't accidentally preclude any of them later.

| | Import | Export |
|---|---|---|
| On demand | Settings UI, manual file pick (exists today for profiles/skills) | Settings UI, manual download (exists today); "Create Pack" builder (§7) |
| Scheduled | As a step in an update **Routine** (recheck/reinstall) | As a step in a backup/export **Routine** |
| At provisioning | Install a preset **Bundle** on first run / new-device setup (the Ansible-like use case) | — |
| Version control | Clone a pack's git repo into `~/.packs/<vendor>/<name>/` | Push a pack folder as a git repo |
| Marketplace (future) | Install from a community library | Publish to a community library |

## 9. Security scanning on import and update

Every import or update, not just community-sourced ones, should pass a **deterministic scan by default** — static analysis, not an LLM, so results are reproducible and can't be talked out of a decision by adversarial content in the pack itself:

- Manifest schema validation, zip-slip path validation (any embedded file path must resolve inside the intended install directory).
- Static analysis of tool/app script content for dangerous patterns (network egress, credential/secret file access, known-malicious signatures).
- Dependency-list checks against known-vulnerable package advisories.

An **optional, explicitly opt-in "enhanced pack scanning" setting** can add an LLM review pass *in addition to*, never instead of, the deterministic baseline. Flag for the team: an LLM scanner is itself a target — a pack could carry content aimed at the reviewing model (prompt injection embedded in a script comment or manifest field), so this needs to be designed as an additional signal, not a gate that fully replaces static checks.

## 10. UI: Packs as their own surface

A new **Packs** area in Settings lists installed packs (browsable by vendor), their lock state, source, and install path — distinct from the existing per-type tabs (Agents, Skills, Custom Tools, Apps), which keep working exactly as they do today for direct single-item management. Items that belong to an installed pack should cross-link from their per-type tab into the pack's entry in the new Packs UI, so the two surfaces don't feel disconnected. This is also where the "Create Pack" builder (§7) lives.

## 11. Explicitly out of scope for near-term work

- **Community library** (search, browse, rate, comment, publish) — the long-term destination this architecture should not preclude, but it needs its own design pass (hosting, moderation, any commercial/licensing model) and real team bandwidth. Named here so it isn't lost, not scheduled.
- Anything requiring a hosted registry or payment/licensing infrastructure.
- **Vendor namespace verification.** Since a pack built on-device defaults its `author`/`vendor` to the local user (§2, §4), namespace collisions aren't a live concern for now — there's no shared namespace until publishing exists. This becomes a real question only once a community library (above) is real, and can be deferred until then.

## 12. Proposed phased breakdown

Phases are ordered by dependency, sized to be independently schedulable:

- **Phase A — Generalize the transport.** Polymorphic item model (profile/skill/tool/app, routine added when B lands), zip container only when an item carries real files, per-item provenance (`publisher`/`editable`) with server-side write gating, manifest metadata fields (§4). This is the previously-scoped, most concretely-detailed phase and can start independently of everything below.
- **Phase B — On-disk standardization + migration.** Migrate storage to `~/.packs/<vendor>/<name>/<type>/` and `~/.packs/custom/<type>/`; tree-crawl manifest discovery; add Routine as a fifth packable kind; **a concrete, reviewed migration path for existing installs (§5)** — this is a required deliverable of the phase, not a follow-up.
- **Phase C — Pack builder & dependency discovery.** The "Create Pack" flow (manual and agent-assisted), embedding cloneable items from other packs, best-effort dependency resolution plus the import-time missing-dependency check (§7). Depends on A; benefits from B for enumeration but doesn't strictly require it.
- **Phase D — Read-only enforcement.** Filesystem-level locking, the privileged installer/updater component, "uncloneable" manifest flag + UI honoring, clone-to-customize. Depends on B (needs the standardized layout to lock meaningfully).
- **Phase E — Git-backed packs.** Pack folder as a git working tree; import-from-clone, export-as-push, update-check via git fetch/diff. Depends on B. This also reopens the previously-deferred "versioning / check for updates" work, now with git as the concrete transport instead of a bespoke registry.
- **Phase F — Security scanning gate.** Deterministic scan on every import/update; opt-in LLM-enhanced pass. Should land no later than E, ideally incrementally starting alongside A/B since it's good hygiene regardless of source.
- **Phase G — Dedicated Packs Settings UI.** Cross-linked from the existing per-type tabs; hosts the Phase C builder.
- **Phase H (long-term, not scheduled) — Community library.**

## 13. Open questions for the dev team

- **Routine secrets.** A packed Routine's Tasks may reference a specific broker/integration connection (e.g. "send an email via *my* Google account"). Sharing that routine as a pack has an obvious secret/credential leak shape that needs its own design pass — this is probably the single riskiest item-kind addition here.
- **Privileged installer mechanism.** New dedicated component, or built adjacent to the existing broker/supervisor architecture in `integrations/`?
- **"Uncloneable" investment level.** Given the document's own position that this can't be real DRM, how much engineering investment is worth putting behind the courtesy version (versus just shipping the honor-system UI flag and moving on)?
- **Scanning cost tiering.** Personal/local pack imports need scanning that's fast and free; community-library-grade scanning (pre-publish) can afford to be heavier and server-side. Where's the line, and does Phase F need to design for both tiers from the start?
- **Dependency-reference tightening.** How much of §7's implicit reference gap (free-text tool references in skill prompts/task instructions) is worth making structural now, versus accepting best-effort resolution plus the import-time missing-dependency check as good enough for a first pass?
- **Migration ownership.** Who scopes and owns the concrete migration path in Phase B, and does the existing `migrations/` runner fit, or does this need its own mechanism given it also touches container-mounted paths?
