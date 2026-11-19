# Codemap

## Directory structure

| Path | Purpose | Key entry points | Wiki pages |
|------|---------|-----------------|------------|
| `main.py` | Server entry point — loads env/config and starts aiohttp | `main.py:main()` | [[App Startup]] |
| `config/` | Config loading: `config.yaml` + env-var interpolation → `AppConfig` | `config/__init__.py:load_config()` | [[AppConfig]] |
| `settings.py` | Runtime-editable settings (`settings.json`) — providers, feature flags. Distinct from `AppConfig`, which is the static startup config | `settings.py:load_settings()` | [[Settings]] |
| `agents/` | `AgentProfile` definitions (saved configs: model, prompt, skills, inference params) | `agents/_agent_profiles.py` | [[AgentProfile]] |
| `agent_core/` | Per-turn agent primitives: turn loop, hooks, events, context/history, provider protocol, skill loading, tool schema. **Live successor to `sdk/`.** | `agent_core/turn/`, `agent_core/hooks/`, `agent_core/events/`, `agent_core/context/`, `agent_core/providers/`, `agent_core/skills/`, `agent_core/tools/` | [[Turn Lifecycle]], [[Event System]], [[Context Compaction]], [[Hooks System]], [[Provider Abstraction]], [[AgentEvent]], [[ConversationHistory]] |
| `agent_runtime/` | Orchestration above a single turn: session/run management, sub-agent spawn, compaction scheduling | `agent_runtime/_factory.py` (`build_agent`), `agent_runtime/_runtime.py` (`AgentRuntime`), `agent_runtime/_runner.py`, `agent_runtime/_spawn.py` | [[build_agent]], [[Multi-Agent Architecture]], [[Turn Lifecycle]] |
| `providers/` (top-level) | App-level provider name resolution and connection brokering, distinct from the portable protocol in `agent_core/providers/` | `providers/__init__.py` | [[Provider Abstraction]] |
| `sdk/` | **Dead.** Every subpackage is empty except `__pycache__`; nothing imports from it. Fully superseded by `agent_core/` + `agent_runtime/`. Not documented as live anywhere in this wiki — a candidate for deletion. | — | — |
| `server/` | aiohttp app factory + ~23 HTTP route modules (`_*_routes.py`) | `server/aiohttp_app.py:create_app()` | [[API Routes]], [[App Startup]] |
| `server/_agent_run_routes.py` | Chat/run HTTP surface — adapts the legacy chat wire contract onto `agent_runtime.AgentRuntime`, with resumable/cursor-addressed run replay (`run_id`/`seq`). **Replaces the old `server/message_handler.py`, which no longer exists.** | `start_agent_run()` | [[Turn Lifecycle]], [[API Routes]] |
| `server/ui/` | React 18 + Vite frontend, organized by feature folder (`features/*`), each with its own context provider | `server/ui/src/main.jsx` | [[Frontend Architecture]] |
| `tools/` | LLM-callable tool implementations, grouped by category | `tools/browser/`, `tools/virtual_computer/`, `tools/memory/`, `tools/integrations/`, `tools/custom_tools/`, `tools/generation/`, `tools/desktop/`, `tools/web/`, `tools/scratchpad/`, `tools/misc/` | [[Tool Architecture]], [[Browser Automation]], [[Sandboxed Code Execution]] |
| `browser/` (top-level) | The actual browser runtime (Playwright session pool, profile persistence) that `tools/browser/` wraps as an LLM tool — don't conflate the two | `browser/runtime.py`, `browser/session_pool.py` | [[Browser Automation]] |
| `skills/` (top-level) | Skill storage, policy, and tool-category resolution — distinct from `agent_core/skills/`, which loads a skill into a running turn | `skills/_store.py`, `skills/_tool_categories.py` | [[Skill System]] |
| `integrations/` | Application-level catalog, operations, and grants for tool integrations (what an agent is allowed to do) | `integrations/service.py` | [[Integrations Architecture]] |
| `brokering/` | Credential vault + broker-subprocess platform underneath integrations. Also brokers model-provider connections (LLM API keys), via a dedicated `llm_proxy` broker — not just tool integrations like Gmail/Calendar | `brokering/_control.py`, `brokering/_rpc.py` | [[Credential Brokering]] |
| `conversations/` | Conversation persistence: event log writer, conversation store/cache, metadata, folders, title generation | `conversations/_conversation_store.py`, `conversations/_events_log.py` | [[ConversationHistory]] |
| `tasks/` | Autonomous Routine engine (Routine → Run → Task DAG → TaskResult); formerly "Goals" — the rename reaches `RoutinesConfig` and the DB, not just UI labels | `tasks/_runner.py`, `tasks/_executor.py` | [[Task Engine]] |
| `artifacts/` | File-output index: dedups generated files by id, reconciles present/missing on disk | `artifacts/_store.py`, `artifacts/_index_writer.py` | [[Artifacts]] |
| `packs/` | Export/import format for agent profiles + skills, bundled as one shareable unit | `packs/_pack.py` | [[Pack]] |
| `custom_apps/` | Thin: just the public `@action` decorator for authoring Custom App backends. The real feature (routing, execution) lives in `server/_custom_app_routes.py` / `server/_custom_app_runner.py` | `custom_apps/__init__.py` | — (described under [[API Routes]]) |
| `models/` | Shared Pydantic/type models — currently a 1-line facade, still thin | `models/__init__.py` | — |
| `migrations/` | One-time data migration scripts (e.g. `_013_goals_to_routines.py` — confirms the Goals→Routines rename) | `migrations/_runner.py` | — |
| `setup/` | First-run setup wizard logic | — | — |
| `utils/` | Shared utilities (caching, etc.) | `utils/cache.py` | — |
| `container/` | Inference client/server, accessibility tree, grounding | `container/inference_client.py` | — |
| `scripts/` | Runtime/build helper scripts, including the UI event-type generator | `scripts/generate_ui_event_types.py` | [[Frontend Architecture]] |
| `tests/` | Unit, e2e, integration test suites | `tests/unit/`, `tests/e2e/`, `tests/integration/` | — |
| `docs/` | Design docs and architecture notes (including this wiki) | `docs/sdk_semantics.md`, `docs/integrations.md`, `docs/wiki/` | — |
| `plans/` | Proposals and follow-ups — **not necessarily implemented behavior.** Don't treat as a source of truth for current code. | — | — |
| `desktop/` | The native Tauri desktop application (Windows/macOS/Linux installer, Rust + web). A separate product from the Python/React app this wiki documents — see its own `desktop/README.md`. Out of scope here. | — | — |

## Where to look for common tasks

| Task | Start here |
|------|-----------|
| Add a new agent tool | [[Adding a New Tool]] |
| Add a new HTTP API route | [[Adding a New API Route]] |
| Add a new agent profile | `agents/_agent_profiles.py` → `agents/default_profiles/` |
| Add a new integration provider | [[Integrations Architecture]] → `integrations/catalog/` |
| Add a new credential-brokered provider (tool integration or model provider) | [[Credential Brokering]] → `brokering/catalog.py` |
| Understand the chat/run request lifecycle | [[Turn Lifecycle]] |
| Understand how events stream to the UI | [[Event System]] |
| Add a new frontend feature | [[Frontend Architecture]] → `server/ui/src/features/` |
| Understand context window management | [[Context Compaction]] |
| Add a new routine/scheduling feature | [[Task Engine]] |
| Understand sub-agent spawning | [[Multi-Agent Architecture]] |
| Understand how skills grant tools | [[Skill System]] |

## Entry points

- **Server start:** `main.py:main()` — loads env, calls `server/aiohttp_app.py:create_app()`
- **Chat/run API:** `POST /api/chat` → `server/_agent_run_routes.py:start_agent_run()` → `agent_runtime.AgentRuntime` → `RunSession` → `AgentRunner`
- **React root:** `server/ui/src/main.jsx` → feature-folder app shell
- **Test runner:** `just unit` / `just e2e` / `just test-ui`
- **Config:** `config.yaml` (root); `config/__init__.py:load_config()` (static startup config, cached); `settings.py` (runtime-editable settings)

## Known gaps noticed during the 2026-10-18 regeneration (not fixed, flagged for follow-up)

- **CSRF coverage gap:** the CSRF middleware checks `{POST, PUT, DELETE}` but not `PATCH`. Several routes (conversation/folder/provider updates) use `PATCH` and are effectively unprotected. See [[API Routes]].
- **`sdk/` is dead code** left in the tree (empty subpackages, zero imports) — candidate for deletion, not wiki content.
- **"Multi-agent instances"** (the README's work/home/project isolated-context feature) was not found under `agent_core/`/`agent_runtime/` during this pass — likely a deployment-level concept rather than application code. Needs a follow-up look if it's meant to be documented here.
