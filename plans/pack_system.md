# Omnideck Pack System — architecture direction (RFC)

**Status:** Direction-setting document for team discussion. Not an execution plan — no code changes are proposed to land from this document as-is.

**See also:** `plans/skills_standard_adoption.md` — a companion doc asking whether the Skill item kind specifically should adopt the open Agent Skills (`SKILL.md`) format rather than a bespoke shape. Its open questions are threaded into the relevant sections below (§3, §5, §9, §12) rather than duplicated wholesale.

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
| **Vendor** | The publishing namespace a pack was authored under — an org, a team, a community author, or the user's own publisher handle. Local/unpublished Custom packs (§2.1) carry no vendor at all; it's only asked for the first time the user exports/publishes a pack, then reused from Settings after that (§4). See §11 on why cross-vendor collisions aren't a live concern yet. |
| **Locked / editable** | Per-item (and per-pack) flag: whether the agent or user can modify it in place, versus needing to clone it into their own custom space first. |

### 2.1 Provenance tiers

Storage location, lock state, and visibility all derive from which of three tiers an item belongs to — this is the organizing idea behind §5 and §6 below:

| Tier | What it is | Editable? | Where it lives | Discoverable how |
|---|---|---|---|---|
| **Core** | Ships inside the Omnideck application itself — default profiles, built-in tool categories, and equivalents. Not something a user installed. | No, not through any pack mechanism. Updated only by upgrading Omnideck. | App-managed area, not a user data directory (today: things like `agents/default_profiles/*.json`). This RFC doesn't change core storage, only names it as a distinct tier. | Not browsed in the Packs UI as a "pack" — it's the platform baseline. |
| **Contrib** | An installed pack from anyone other than the user — a vendor, a team, a community author, a colleague's shared pack. | No, locked by default (§6). Only path in is clone-to-customize, which promotes an item to Custom. | Hidden, under `~/.contrib/<vendor>/<pack-name>/` (§5). | Dedicated Packs UI (§10), not the per-type tabs. |
| **Custom** | Anything the user (or the agent, on the user's behalf) owns and can freely edit — built from scratch, or cloned out of a Contrib pack. | Yes, always. | Visible, either in the native per-type tree (standalone items) or `~/packs/<pack-name>/` (items combined into a pack) — see §5. | The existing per-type tabs (Agents, Skills, Custom Tools, Apps), exactly as today, plus the Packs UI for anything combined into a pack. |

A published Custom pack and an installed Contrib pack are the same manifest shape viewed from opposite ends: sharing your own pack (Phase E, git push) is what turns it into someone else's Contrib pack the moment they pull it.

## 3. Item kinds in scope

Profile, Skill, Tool, App, **Routine** (new addition per this discussion — a `Routine` + its `Task`s, so "check for updates" or any other scheduled workflow becomes packable and shareable the same way a skill is).

**Skill is a special case among these five.** The other four (Profile, Tool, App, Routine) have no external format to reconcile with — this RFC's manifest/on-disk design is the only design that will ever exist for them. Skill does: the open Agent Skills format (`SKILL.md` — folder, YAML frontmatter, optional bundled `scripts/`/`references/`/`assets/`) is already adopted across a long list of other agent products, with its own live registry (`skills.sh`). `plans/skills_standard_adoption.md` makes the case in full; the short version is that Skill packaging should default to *wrapping or adopting* that format rather than inventing a sixth one, and every place below where Skill's shape is assumed to mirror the other four item kinds is flagged accordingly.

## 4. Manifest metadata (discovery & UX)

These fields exist purely to make a pack presentable and searchable — in the near-term UI (§8) and the eventual community library (§9) alike. They live on the **pack** manifest (the discoverable/shareable unit), not on individual items inside it:

| Field | Required | Type | Notes |
|---|---|---|---|
| `title` | Yes | string | Display name of the pack. |
| `author` / `vendor` | Only at first publish/export | string | Omitted entirely for local-only packs — Custom provenance (§2.1) is implicit, never stored as a literal `vendor: custom` value. The first time a user exports or publishes a pack anywhere (zip share, git push, community library), they're prompted once for a persistent **publisher handle** — expected to double as their git username — which is then cached in Settings and reused silently for every later pack. Editable from Settings afterward, but not surfaced prominently there; most users set it once and never look at it again. |
| `short_description` | Yes | plain text | Card/list-view summary. |
| `long_description` | No | markdown | Full detail view. |
| `category` | No | string | For browse/filter grouping once there's enough volume to need it. Same vocabulary as the skill-category/group concept proposed in `plans/skills_standard_adoption.md` §5 — worth deciding whether these are literally the same field rather than two parallel grouping systems. |
| `images` | No | array | First entry is the card thumbnail; remaining entries populate a detail-view carousel. |

## 5. On-disk layout

Today, storage is scattered: profiles and skills live under the app server's `home_dir` as one JSON file per record; custom tools split a `registry.json` (app `home_dir`) from script files (the *container-mounted* `virtual_computer.home_dir`); apps are bare directories under the container's `apps/`, with their manifest (`omnideck.json`) sitting right alongside them, visible and directly editable; routines/tasks have their own file store. Standardizing packs means standardizing this too — but an earlier draft of this section proposed folding *all* of it, including a user's own custom apps, under a single dot-folder tree (`~/.packs/custom/<type>/`). That's wrong on two counts: it buries something a user can see and edit today (`apps/<slug>/omnideck.json`) the same way a locked, foreign, installed pack is buried, *and* it uses one name (`~/.packs`) for two things that need to read as opposites — the user's own open workspace and a hidden vendor area. The layout below fixes both: **two top-level roots with names that say what they are**, `~/packs/` (no dot — the user's own, browsable, git-friendly pack workspace) and `~/.contrib/` (dot — hidden, locked, installed-from-elsewhere).

**Layout, organized by provenance tier (§2.1):**

```
<native-root>/                     # container-mounted; see root-location note below
  app/
    okf-app/                       # standalone custom item — lives here directly, fully editable
  profile/
    my-agent/
  skill/
    quick-notes/
  tool/
  routine/

  packs/                           # visible — the user's own pack workspace
    okf-kit/                       # a custom pack the user combined from 2+ existing items
      manifest.json
      app/okf-app/                 # real files now live here...
      profile/okf-agent/
      skill/okf-skill/

  .contrib/                        # hidden — installed, locked, foreign packs
    acme/
      onboarding-kit/
        manifest.json
        app/  profile/  skill/  tool/  routine/
```

with, back in the native tree:

```
<native-root>/app/okf-app -> <native-root>/packs/okf-kit/app/okf-app   # ...and a symlink left in its place
```

**A standalone custom item lives directly in its native per-type folder** — no pack, no indirection, editable in place exactly like today's `apps/<slug>/`.

**Combining two or more custom items into a pack always materializes, and always leaves a symlink behind.** Earlier drafts weighed a reference-only manifest (items stay put; the pack is just a list of pointers) against copying on creation, and landed on doing both at once rather than picking one:

- `Create Pack` **moves** the selected items' real files into `~/packs/<pack-name>/<type>/`, and **replaces each one's old native-folder location with a symlink** pointing at the new spot. `~/packs/` is deliberately visible, not dot-prefixed — a user should be able to `ls`/browse it and immediately understand it as their own pack workspace, not app internals.
- The pack folder is a genuine, self-contained unit from the moment it's created — already the right shape to git-push or zip-export later (§8, Phase E) with no separate "aggregate for export" step, and it's a natural place for the user to `git init` directly if they want the whole thing version-controlled.
- Nothing that referenced the item by its native path breaks: the per-type UI tabs, any tool/skill/task that names it, a user just browsing `app/` looking for their app — all still resolve through the symlink.
- This keeps the behavior uniform whether or not the user thinks about the reference-vs-copy distinction at all — there's exactly one thing "Create Pack" does to existing items, not two divergent code paths to build, test, and explain.

**Symlink lifecycle is enforced at delete time, nowhere else.** Deleting an item through the app must also delete its symlink, wherever the item currently lives; deleting a pack must delete every member's symlink along with the pack folder itself. A dangling symlink left behind by either operation is a bug. This is deliberately the *only* place this gets enforced — most users never touch these directories directly, and for the ones who do, out-of-band edits (deleting a symlink by hand, moving a folder outside the app) are on them to keep consistent; the app doesn't scan for or repair drift it didn't cause. A periodic filesystem-wide consistency check is a real idea but a separate scope from this RFC (§11).

Symlinks are assumed reliable without a fallback path: every directory in this layout lives inside the Omnideck-managed Linux container, never directly on a host filesystem a user browses with Explorer/Finder — so host-OS symlink limitations (e.g. Windows requiring elevated privileges) don't apply. If a future surface ever exposes this tree directly on a host filesystem where symlinks aren't reliable, that surface owns solving it; it's not a constraint on this design.

**Contrib packs never get symlinked into the native tree.** Their files live under `~/.contrib/<vendor>/<pack-name>/` from install and stay there, hidden — they're locked and not meant to be discoverable/editable as if they were the user's own. "Clone to customize" (§6) is the only path from Contrib to Custom, and it lands the clone as a standalone item directly in the native per-type folder — the same "lives here directly" case above — not pre-packaged, unless the user explicitly folds it into a custom pack afterward (at which point the usual materialize-and-symlink applies, into `~/packs/`).

- **Root location.** Team direction: user-owned content (Custom and Contrib alike) lives under the container-mounted `virtual_computer.home_dir`, unified — apps/tools already need execution access there, and it means a pack (or a git-cloned repo, Phase E) is never split across two filesystems. Core content (§2.1) stays under the app-managed area of `settings.home_dir`, since it isn't user data — it ships with, and is updated by, Omnideck itself, not the pack installer.
- **`skill/` is drawn above as a flat file-per-item folder like the other four types, and that's only correct if the Skill format decision in `plans/skills_standard_adoption.md` goes unadopted.** If Skill packaging moves to `SKILL.md`, each skill needs its own subfolder (`skill/<skill-id>/SKILL.md` plus optional `scripts/`/`references/`/`assets/`) rather than one flat JSON file, in the native tree exactly as much as inside a pack — a standalone custom skill needs somewhere to hold `SKILL.md` too. Worth resolving before Phase B locks in a layout, since retrofitting nested folders after migration is strictly more work than designing for it up front.

**Migration.** Landing this layout means moving every existing on-disk profile, skill, tool, and app into the native tree — today's users, however few, already have real data in the old locations. All of it migrates as standalone Custom items (nothing is packed yet, so no symlinks are needed at migration time). The install base is small right now (no community yet), so the blast radius is limited, but a broken or lossy migration on someone's existing install is still a real, user-visible failure, not a cosmetic one. This needs a concrete, reviewed migration path from the dev team before Phase B ships (see §12) — not an afterthought bolted onto the storage change. Worth checking whether the existing `migrations/` runner (already used for schema changes like `migrations/_013_goals_to_routines.py`) is the right vehicle.

## 6. Read-only enforcement and "clone to customize"

- Installed pack items are **locked by default** (`editable: false`). Enforcement is filesystem-level (read-only permissions on the pack's directory tree), not just a disabled button in the UI — the agent's own tool-execution path and a user poking at files directly should both be physically unable to mutate a locked pack.
- The only path that's allowed to write a locked pack (installing it fresh, or applying an update) should go through an **isolated, elevated-trust component**, not the same process that executes LLM-invoked tools. Omnideck already has a precedent for this shape — `integrations/brokers/*` are separate sandboxed processes holding capabilities the main agent path doesn't have, invoked over a UDS RPC (`integrations/broker_client`). The pack installer/updater should follow that same separation-of-privilege pattern; whether it *reuses* broker infrastructure or is its own analogous component is a design question for the team, not decided here.
- **"Uncloneable" is a courtesy flag, not real protection.** A manifest can optionally mark a pack as discouraging clone-to-customize, and the UI should honor it (hide/disable the affordance). The document should be explicit, and any implementation should be explicit to users, that this is friction against accidental copying — not DRM. A determined user with filesystem access can always route around it, and the design must not oversell otherwise.
- "Clone to customize" copies (not moves) a locked Contrib pack's item(s) into the native per-type folder (`<native-root>/<type>/`, §5) as standalone Custom items, flips `editable: true`, and keeps `source.publisher` for attribution. If the user later combines a clone with other custom items into a pack, it's aggregated the same way any custom item is (§5) — moved into the new pack folder with a symlink left behind in its place.

## 7. Building a pack: selection and dependency discovery

Packs need an authoring path, not just an installing one:

- **Manual builder**: a "Create Pack" flow (Settings UI, §10) where the user finds/selects items from their own library, fills in the manifest fields from §4, and gets back a pack. Per §5, this is always a materialize-and-symlink operation on the selected items, never a reference-only manifest: their real files move into the new pack folder and a symlink is left behind at each one's old native location.
- **An item belongs to at most one pack at a time.** If the user selects an item that's already a member of another pack, or a locked Contrib item that hasn't been cloned yet (only cloneable items qualify — not `uncloneable`, §6), the builder clones it first, producing a new, independent item with its own identity, then moves *that* into the new pack. Kept deliberately simple: no shared ownership, no "which pack is the real one" ambiguity — at the cost of the clone diverging immediately, since edits to one no longer touch the other. Sharing one entity across multiple packs without forking it is out of scope for now (§11).
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
| Version control | Clone a pack's git repo into `~/.contrib/<vendor>/<name>/` | Push a pack folder from `~/packs/<name>/` as a git repo |
| Marketplace (future) | Install from a community library | Publish to a community library |

### 8.1 Importing an unpackaged ("agnostic") repo

Not every repo a user wants to pull from will carry an Omnideck pack manifest — someone's personal collection of skills and scripts on GitHub, authored with no Omnideck awareness at all, is exactly the case this needs to cover. Team direction from this discussion: support this for **all five item kinds from the start**, not just Skill.

- Each item kind needs a **minimal, standalone, self-describing descriptor** that identifies it without a pack manifest wrapping it — a folder or file that says "I am a Tool" (or Profile, Routine) the same way `SKILL.md` already does for Skill and `omnideck.json` already does for App. Skill and App already have this; **Tool, Profile, and Routine do not yet, and need one designed.** This is new scope beyond the original RFC's Phase A polymorphic item model — it's a *format* question (what makes a bare folder recognizable as a Tool with no wrapping manifest), not just a container question.
- Import walks the cloned repo, recognizes whichever descriptors it finds — a repo can mix kinds, a `skill/` folder here, a `tool/` folder there — and **synthesizes a `manifest.json` from what it found** rather than requiring the source repo to have authored one.
- Because it arrived from outside the user's own install, the result lands as a **Contrib pack** (§2.1, §5), under `~/.contrib/<inferred-or-user-named-vendor>/<repo-name>/`, locked by default like any other Contrib pack, and goes through the same security scan (§9) as a manifest-carrying import — an absent manifest is a reason for *more* caution, not less.
- This reframes "pack" and "agnostic import" as the same mechanism rather than two features: a manifest, when present, is authored up front by the source repo; when absent, it's inferred at import time from recognized per-item descriptors. "Managing things without packs," raised in this discussion, turns out to already be covered by §5's standalone-item case (Custom items with no pack at all) — what's actually missing is just the descriptor formats above, so recognition works for kinds beyond Skill/App.

## 9. Security scanning on import and update

Every import or update, not just community-sourced ones, should pass a **deterministic scan by default** — static analysis, not an LLM, so results are reproducible and can't be talked out of a decision by adversarial content in the pack itself:

- Manifest schema validation, zip-slip path validation (any embedded file path must resolve inside the intended install directory).
- Static analysis of tool/app script content for dangerous patterns (network egress, credential/secret file access, known-malicious signatures).
- Dependency-list checks against known-vulnerable package advisories.
- **Vendor/pack-name collision check.** If the exact `<vendor>/<pack-name>` pair being imported already exists under `~/.contrib/`, this is surfaced to the user rather than silently overwritten or merged — most likely two unrelated publishers picked the same strings, since vendor identity isn't verified (§11). The importer offers a suggested, editable alternative name (e.g. `<pack-name>-2`) to install under instead.

An **optional, explicitly opt-in "enhanced pack scanning" setting** can add an LLM review pass *in addition to*, never instead of, the deterministic baseline. Flag for the team: an LLM scanner is itself a target — a pack could carry content aimed at the reviewing model (prompt injection embedded in a script comment or manifest field), so this needs to be designed as an additional signal, not a gate that fully replaces static checks.

If Skill packaging adopts `SKILL.md` (`plans/skills_standard_adoption.md` §6), its `allowed-tools` (pre-approved tool allowlist) and `compatibility` (declared environment requirements) frontmatter fields are a ready-made starting schema for what this scanner checks on a Skill item specifically, rather than designing that schema from nothing — worth using as the template even if the other four item kinds need their own scan rules.

## 10. UI: Packs as their own surface

A new **Packs** area in Settings lists every pack the user has — their own Custom packs (`~/packs/`) and installed Contrib packs (`~/.contrib/<vendor>/`, browsable by vendor) side by side, distinguished by a clear lock-state badge, with source and install path shown for Contrib entries. Distinct from the existing per-type tabs (Agents, Skills, Custom Tools, Apps), which keep working exactly as they do today for direct single-item management. Items that belong to any pack should cross-link from their per-type tab into the pack's entry in the new Packs UI, so the two surfaces don't feel disconnected. This is also where the "Create Pack" builder (§7) lives.

## 11. Explicitly out of scope for near-term work

- **Community library** (search, browse, rate, comment, publish) — the long-term destination this architecture should not preclude, but it needs its own design pass (hosting, moderation, any commercial/licensing model) and real team bandwidth. Named here so it isn't lost, not scheduled.
- Anything requiring a hosted registry or payment/licensing infrastructure.
- **Vendor identity verification.** Two different real people can pick the same publisher handle (§2, §4) with nothing stopping them — there's no registry checking uniqueness. Accepted as fine for now; the one concrete case this does need to handle — an exact `<vendor>/<pack-name>` collision on import — is a filesystem problem, not an identity one, and is covered in §9. Verifying that a handle actually belongs to who it claims to is a real question only once a community library (above) exists, and stays deferred until then.
- **Combining packs / sharing an item across packs.** §7 keeps pack membership single — an item belongs to at most one pack, and joining a second one means cloning an independent copy. The natural follow-up this raises — a pack that recombines several existing sub-packs, sharing entities the way a "Marketing Super Pack" might reuse skills already living in smaller packs — isn't solved here. Likely direction: a repo hosting **multiple sibling packs, each with its own manifest**, that a user opts into individually, rather than item-level sharing across packs. Named here so it isn't lost, not designed further.
- **Filesystem-wide integrity/consistency checking.** A periodic "doctor" pass across all native storage, catching drift beyond what the on-delete symlink cleanup (§5) already handles. Worth a note so it isn't lost, but a separate scope from this RFC.

## 12. Proposed phased breakdown

Phases are ordered by dependency, sized to be independently schedulable:

- **Phase A — Generalize the transport.** Polymorphic item model (profile/skill/tool/app, routine added when B lands), zip container only when an item carries real files, per-item provenance (`publisher`/`editable`) with server-side write gating, manifest metadata fields (§4), and **minimal standalone descriptor formats for Tool, Profile, and Routine** (§8.1) so each kind is self-describing without a wrapping manifest — Skill and App already have this (`SKILL.md`, `omnideck.json`). This is the previously-scoped, most concretely-detailed phase and can start independently of everything below. Note: "zip only when an item carries real files" currently means Skill never needs one — today's flat `SkillRecord` has none. That assumption flips if `SKILL.md` adoption lands (`plans/skills_standard_adoption.md` §6), since a skill folder can carry `scripts/`/`references/`/`assets/` — worth deciding the Skill format question before or alongside Phase A rather than after, so this phase's polymorphic item model doesn't need revisiting once Skill grows a files case the other three don't have yet.
- **Phase B — On-disk standardization + migration.** Migrate storage to the three-tier layout (§5): a unified native per-type tree for standalone Custom items, `~/packs/<name>/<type>/` for combined Custom packs, `~/.contrib/<vendor>/<name>/<type>/` for Contrib packs; tree-crawl manifest discovery; add Routine as a fifth packable kind; the materialize-and-symlink mechanics for combining Custom items into a pack, plus symlink lifecycle cleanup on delete; **a concrete, reviewed migration path for existing installs (§5)** — this is a required deliverable of the phase, not a follow-up.
- **Phase C — Pack builder & dependency discovery.** The "Create Pack" flow (manual and agent-assisted), embedding cloneable items from other packs, best-effort dependency resolution plus the import-time missing-dependency check (§7). Depends on A; benefits from B for enumeration but doesn't strictly require it.
- **Phase D — Read-only enforcement.** Filesystem-level locking, the privileged installer/updater component, "uncloneable" manifest flag + UI honoring, clone-to-customize (landing clones as standalone Custom items per §5/§6). Depends on B (needs the standardized layout to lock meaningfully).
- **Phase E — Git-backed packs.** Pack folder as a git working tree; import-from-clone, export-as-push, update-check via git fetch/diff. Depends on B — a materialized Custom pack folder (§5) is already the right shape for this with no extra aggregation step. This also reopens the previously-deferred "versioning / check for updates" work, now with git as the concrete transport instead of a bespoke registry. For Skill specifically, this phase may already be solved by adopting `SKILL.md`: `skills.sh` is a live git-backed registry (`npx skillsadd <owner/repo>`) for that exact format today — if Skill adopts the standard, Phase E's work for that one item kind may be "point at what exists" rather than "build it," which is worth factoring into sequencing rather than building a parallel mechanism.
- **Phase F — Security scanning gate.** Deterministic scan on every import/update; opt-in LLM-enhanced pass. Should land no later than E, ideally incrementally starting alongside A/B since it's good hygiene regardless of source. Agnostic repo import (§8.1) doesn't get its own numbered phase — it's a capability that falls out once Phase A's descriptor formats, Phase B's layout, and this phase's scanning gate are all in place, so sequence it as a small addition landing alongside or just after F rather than scheduling it separately.
- **Phase G — Dedicated Packs Settings UI.** Cross-linked from the existing per-type tabs; hosts the Phase C builder.
- **Phase H (long-term, not scheduled) — Community library.**

## 13. Open questions for the dev team

- **Routine secrets.** A packed Routine's Tasks may reference a specific broker/integration connection (e.g. "send an email via *my* Google account"). Sharing that routine as a pack has an obvious secret/credential leak shape that needs its own design pass — this is probably the single riskiest item-kind addition here.
- **Privileged installer mechanism.** New dedicated component, or built adjacent to the existing broker/supervisor architecture in `integrations/`?
- **"Uncloneable" investment level.** Given the document's own position that this can't be real DRM, how much engineering investment is worth putting behind the courtesy version (versus just shipping the honor-system UI flag and moving on)?
- **Scanning cost tiering.** Personal/local pack imports need scanning that's fast and free; community-library-grade scanning (pre-publish) can afford to be heavier and server-side. Where's the line, and does Phase F need to design for both tiers from the start?
- **Dependency-reference tightening.** How much of §7's implicit reference gap (free-text tool references in skill prompts/task instructions) is worth making structural now, versus accepting best-effort resolution plus the import-time missing-dependency check as good enough for a first pass?
- **Migration ownership.** Who scopes and owns the concrete migration path in Phase B, and does the existing `migrations/` runner fit, or does this need its own mechanism given it also touches container-mounted paths?
- **Skill format adoption timing.** Does the `SKILL.md` decision (`plans/skills_standard_adoption.md`) need to be resolved *before* Phase A/B lock in the polymorphic item model and on-disk layout, given §5 and Phase A above both note that Skill's shape under adoption diverges from the other four item kinds? Deciding late risks a second migration on top of Phase B's already-planned one.
- **Descriptor format ownership.** Tool, Profile, and Routine each need a minimal standalone descriptor (§8.1) before agnostic repo import can treat them the way Skill/App already work. Designing three new file-shape formats is real, separate work from the polymorphic item model Phase A already scopes — who owns that design, and does it land as part of Phase A or as its own sub-effort ahead of it?
- **Core content's relationship to the pack mechanism.** Core (§2.1) is deliberately kept outside the pack installer/updater — it's versioned with the app, not with `~/packs/` or `~/.contrib/`. Should core content nonetheless be internally shaped like a pack (same manifest fields, same item schema) purely for consistency and code reuse, even though it's never installed/updated/scanned through the pack mechanism? Or is treating it as a wholly separate, simpler thing the right call, given it doesn't need locking, cloning, or discovery?
