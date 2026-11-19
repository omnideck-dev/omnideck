# Wiki Activity Log

## [2026-07-07] bootstrap | 6a5625d

- Initial wiki generation from full codebase scan at commit 6a5625d
- Pages created:
  - [[overview]]
  - [[codemap]]
  - [[glossary]]
  - [[index]]
  - [[AgentEvent]] (entity)
  - [[AgentProfile]] (entity)
  - [[API Routes]] (entity)
  - [[App Startup]] (entity)
  - [[AppConfig]] (entity)
  - [[build_agent]] (entity)
  - [[ConversationHistory]] (entity)
  - [[Task Engine]] (entity)
  - [[Context Compaction]] (concept)
  - [[Event System]] (concept)
  - [[Frontend Architecture]] (concept)
  - [[Hooks System]] (concept)
  - [[Integrations Architecture]] (concept)
  - [[Tool Architecture]] (concept)
  - [[Turn Lifecycle]] (concept)
  - [[Adding a New API Route]] (pattern)
  - [[Adding a New Tool]] (pattern)
- Source docs read: `README.md`, `DEVELOPMENT.md`, `CLAUDE.md`, `docs/sdk_semantics.md`, `docs/integrations.md`
- Key source files read: `main.py`, `server/aiohttp_app.py`, `server/message_handler.py`, `agents/_agent_builder.py`, `agents/_agent_profiles.py`, `agents/types.py`, `sdk/__init__.py`, `sdk/events/_models.py`, `sdk/hooks/_default.py`, `config/__init__.py`, `tasks/__init__.py`, `integrations/__init__.py`, `server/ui/src/App.jsx`, `server/ui/src/DesktopApp.jsx`

## [2026-10-18] full regeneration | 3b839a12

- Triggered by 190 commits / ~741 changed files since the last run (`6a5625d`) — including a full package reorg (`sdk/` → `agent_core/` + `agent_runtime/`, `integrations/` split out `brokering/`, `message_handler.py` replaced by `agent_runtime.AgentRuntime`, Goals renamed to Routines). Treated as a full regeneration rather than a targeted refresh, per the staleness threshold in [[WIKI-PROMPT]].
- Also finished an in-progress `git merge` of `origin/task/wiki` that had stalled on an unrelated README.md conflict; resolved that conflict and completed the merge first.
- Wrote `docs/wiki/WIKI-PROMPT.md` — the prior version described an abandoned source-ingestion schema; this version documents the schema actually in use (code-mapped pages pinned to a `verified_commit`, `.state.yml` freshness tracking, targeted-refresh vs full-regeneration workflow) for the first time.
- Pages created:
  - [[Provider Abstraction]] (concept)
  - [[Multi-Agent Architecture]] (concept)
  - [[Browser Automation]] (concept)
  - [[Sandboxed Code Execution]] (concept)
  - [[Skill System]] (concept)
  - [[Credential Brokering]] (concept) — split out of [[Integrations Architecture]], which now covers the catalog/grants layer only
  - [[Artifacts]] (entity)
  - [[Pack]] (entity)
  - [[Settings]] (entity)
- Pages updated (rewritten against current source, not lightly edited — all were 190 commits stale): [[AgentEvent]], [[AgentProfile]], [[build_agent]], [[Context Compaction]], [[Event System]], [[Hooks System]], [[Turn Lifecycle]], [[API Routes]], [[App Startup]], [[Frontend Architecture]], [[Adding a New API Route]], [[ConversationHistory]], [[Task Engine]], [[AppConfig]], [[Integrations Architecture]], [[Tool Architecture]], [[Adding a New Tool]]
- `docs/wiki/entities/callable_to_json_schema.md` folded into [[Tool Architecture]] (subject moved to `agent_core/tools/_callable_schema.py`, no longer warrants a standalone page)
- `index.md`, `codemap.md`, `overview.md`, `glossary.md` rewritten from the final page set; `.state.yml` bumped to `3b839a12`
- `guides/Using Omnideck at Work.md` repaired: dangling links to pages removed in the prior schema migration, and a factual correction (data lives in a bind-mounted host directory, `~/Omnideck`, not a Docker named volume as previously stated)
- Open questions carried into pages rather than guessed at: multi-agent "work/home/project" instance isolation (README-advertised, not found under `agent_core/`/`agent_runtime/` — possibly a deployment-level concept); whether `features/remoteDesktop/` and `features/customApps/` warrant their own concept pages; master-key rotation for the credential vault; virtual-computer path-escape guarding
- Known gap surfaced (not fixed, flagged in [[API Routes]] and `codemap.md`): the CSRF middleware doesn't cover `PATCH`, and several existing routes use it unprotected
- Scope: five parallel passes split by architectural cluster (agent core/runtime, server/API/frontend, tools/skills, integrations/brokering, conversations/tasks/config), each re-reading current source rather than trusting the stale wiki's specifics
