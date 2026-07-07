# Codemap

## Directory structure

| Path | Purpose | Key entry points | Wiki pages |
|------|---------|-----------------|------------|
| `main.py` | Server entry point — loads env/config and starts aiohttp | `main.py:main()` | [[App Startup]] |
| `config/` | Config loading: YAML + env-var interpolation → `AppConfig` | `config/__init__.py:load_config()` | [[AppConfig]] |
| `agents/` | Agent construction from profiles | `agents/_agent_builder.py`, `agents/_agent_profiles.py` | [[AgentProfile]], [[build_agent]] |
| `sdk/` | Core agent loop: turn execution, hooks, events, context, providers | `sdk/turn/`, `sdk/hooks/`, `sdk/events/`, `sdk/context/`, `sdk/providers/` | [[Turn Lifecycle]], [[Event System]], [[Context Compaction]], [[Hooks System]] |
| `server/` | aiohttp HTTP API + React UI serving | `server/aiohttp_app.py:create_app()` | [[API Routes]], [[App Startup]] |
| `server/message_handler.py` | Bridge: HTTP → agent turn → SSE stream | `handle_user_message()` | [[Turn Lifecycle]] |
| `server/ui/` | React 18 + Vite frontend (JSX, CSS Modules) | `server/ui/src/DesktopApp.jsx`, `server/ui/src/main.jsx` | [[Frontend Architecture]] |
| `tools/` | All LLM-callable tool implementations | `tools/browser/`, `tools/virtual_computer/`, `tools/memory/`, `tools/integrations/`, `tools/custom_tools/`, `tools/generation/`, `tools/desktop/` | [[Tool Architecture]] |
| `integrations/` | Integrations subsystem: supervisor, brokers, vault | `integrations/broker_client/`, `integrations/supervisor/` | [[Integrations Architecture]] |
| `conversations/` | Conversation persistence: history, events, titles, profiles | `conversations/__init__.py` | [[ConversationHistory]] |
| `tasks/` | Autonomous goal/task engine | `tasks/_runner.py`, `tasks/_executor.py` | [[Task Engine]] |
| `models/` | Shared Pydantic/type models (currently thin) | `models/__init__.py` | — |
| `migrations/` | One-time data migration scripts | `migrations/_runner.py` | — |
| `setup/` | First-run setup wizard logic | — | — |
| `utils/` | Shared utilities (caching, etc.) | `utils/cache.py` | — |
| `container/` | Inference client/server, accessibility tree, grounding | `container/inference_client.py` | — |
| `bin/` | Runtime helper scripts | — | — |
| `tests/` | Unit, e2e, integration test suites | `tests/unit/`, `tests/e2e/`, `tests/integration/` | — |
| `docs/` | Design docs and architecture notes | `docs/sdk_semantics.md`, `docs/integrations.md` | — |

## Where to look for common tasks

| Task | Start here |
|------|-----------|
| Add a new agent tool | [[Adding a New Tool]] |
| Add a new HTTP API route | [[Adding a New API Route]] |
| Add a new agent profile | `agents/_agent_profiles.py` → `agents/` dir for defaults |
| Add a new integration provider | [[Integrations Architecture]] → `integrations/supervisor/_catalog.py` |
| Understand the chat request lifecycle | [[Turn Lifecycle]] |
| Understand how events stream to the UI | [[Event System]] |
| Add a new frontend view | [[Frontend Architecture]] → `server/ui/src/DesktopApp.jsx` |
| Understand context window management | [[Context Compaction]] |
| Add a new goal/routine feature | [[Task Engine]] |

## Entry points

- **Server start:** `main.py:main()` — loads env, calls `server/aiohttp_app.py:create_app()`
- **Chat API:** `POST /api/chat` → `server/aiohttp_app.py:chat_handler()` → `server/message_handler.py:handle_user_message()`
- **React root:** `server/ui/src/main.jsx` → `App.jsx` → `DesktopApp.jsx`
- **Test runner:** `just unit` / `just e2e` / `just test-ui`
- **Config:** `config.yaml` (root); `config/__init__.py:load_config()` (cached reader)
