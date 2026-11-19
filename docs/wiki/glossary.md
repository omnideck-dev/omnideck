# Glossary

**Agent** — a configured LLM instance with a name, model, system prompt, inference parameters, and a list of callable tools. Constructed by `AgentFactory.build_agent()` from an `AgentProfile`. See [[build_agent]].

**AgentCapabilities** — the bundle of tools, skills, and capabilities resolved for one agent before a run starts. See [[Turn Lifecycle]].

**AgentEvent** — the event envelope emitted during a turn. Contains a typed payload and agent attribution metadata. Streamed to the UI as JSONL, replayable by `run_id`/`seq`. See [[AgentEvent]], [[Event System]].

**AgentFactory** — builds a `PreparedAgent` from an `AgentProfile`; lives in `agent_runtime/_factory.py`, the successor to the old free function `build_agent()`. See [[build_agent]].

**AgentProfile** — a persisted configuration driving one agent: model, provider, system prompt, skills, and inference parameters. What the user creates in the Agents settings tab. See [[AgentProfile]].

**AgentRuntime** — the app-level entry point that starts and manages runs; `server/_agent_run_routes.py` calls into it instead of the old `message_handler.py`. See [[Turn Lifecycle]].

**Agent Span** — a hierarchical execution context wrapping one agent's work within a turn. Depth 0 = root agent; depth 1+ = sub-agents. Attributed to all events published during the span. See [[Turn Lifecycle]], [[Multi-Agent Architecture]].

**AppConfig** — the Pydantic model holding the static startup configuration, loaded from `config.yaml`. Distinct from [[Settings]], which is runtime-editable. See [[AppConfig]].

**Artifact** — in this codebase, a generated file the agent produced, indexed by `artifacts/`. (Not to be confused with the unrelated "Artifact" publishing concept in other Claude products.) See [[Artifacts]].

**Broker** — a per-integration (or per-model-provider) subprocess that holds decrypted credentials and connects to upstream services, communicating with the app via RPC over a Unix domain socket. See [[Credential Brokering]].

**BrowserRuntime** — the Playwright-backed session/profile manager in top-level `browser/`, wrapped by `tools/browser/` as the LLM-facing tool. See [[Browser Automation]].

**BudgetGuard** — a hook that enforces `max_iterations` on the agent turn loop. See [[Hooks System]].

**Compaction** — the process of summarizing older conversation history when the context window approaches capacity, so the agent can continue without hitting the token limit. See [[Context Compaction]].

**CompactionThreshold** — the fill ratio (0.0–1.0) at which compaction fires. Default 0.75 (75% full). Configurable per AgentProfile.

**Conversation** — a persistent multi-turn exchange between user and agent, identified by a `conversation_id` string, managed via `ConversationStore`. See [[ConversationHistory]].

**ConversationHistory** — a view derived on demand from a conversation's append-only event log (`events.jsonl`), not a stored message list. See [[ConversationHistory]].

**ContextManager** — tracks token usage for a conversation and fires `ContextStrategy` plugins (e.g. `LLMCompactionStrategy`) when fill ratio crosses the threshold. See [[Context Compaction]].

**CSRF** — Cross-Site Request Forgery guard. Mutating API calls require `X-Requested-With: XMLHttpRequest`. **Known gap:** the current middleware covers `POST`/`PUT`/`DELETE` but not `PATCH` — see [[API Routes]].

**EventDispatcher** — per-turn fan-out publisher in `agent_core/events/`, delivering `AgentEvent` objects to all registered subscribers (SSE bridge, event-log writer). See [[Event System]].

**Goal** / **Routine** — an autonomous task with a name, prompt, schedule, and profile, structured as a DAG of tasks within a run. Renamed from "Goal" to "Routine" at the code level (`RoutinesConfig`, `migrations/_013_goals_to_routines.py`), not just in the UI. See [[Task Engine]].

**Integration** — a credentialed connection to an external service (Gmail, iCloud), governed by `integrations/`'s catalog/grants and executed through a [[Credential Brokering|broker]] subprocess. See [[Integrations Architecture]].

**JSONL** — JSON Lines format: one JSON object per line, used for the SSE event stream from the backend to the frontend and for `events.jsonl` conversation persistence.

**Message Group** — one assistant message plus all its immediately-following tool-call results. Compaction never splits a group, preventing orphaned tool results. See [[Context Compaction]].

**Model Provider Connection** — a brokered connection to an LLM provider's API (OpenAI/Anthropic/OpenRouter/OpenAI-compatible), routed through a dedicated `llm_proxy` broker that injects the real auth header over a local HTTP proxy so the key never enters the app or agent process. See [[Credential Brokering]], [[Provider Abstraction]].

**Nudge** — a user message injected into a running turn via `POST /api/nudge`. Spliced into history before the next model call, without starting a new turn.

**PreparedAgent** — the object `AgentFactory.build_agent()` returns: model, system prompt, inference options, and resolved tool list, ready to run. See [[build_agent]].

**Profile** — shorthand for [[AgentProfile]].

**Provider** — an LLM inference backend: Ollama (local), OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint. Configured in Settings → Providers. See [[Provider Abstraction]].

**RunSession** — the per-run object in `agent_runtime/` that owns a run's lifecycle (start, stop, nudge, sub-agent spawn) across one or more turns. See [[Turn Lifecycle]].

**Settings** — runtime-editable configuration (`settings.json`): providers, feature flags. Distinct from [[AppConfig]], which is loaded once at startup. See [[Settings]].

**Skill** — a reusable, stored capability bundle (`skills/`) loaded into a conversation at runtime (`agent_core/skills/`). Augments the system prompt and can grant additional tool categories. See [[Skill System]].

**SkillRecord** — the stored form of a skill on disk, distinct from the runtime `Skill` object loaded into a turn. See [[Skill System]].

**Supervisor** — the long-lived process that owns the credential vault and manages broker subprocesses. See [[Credential Brokering]].

**Tool Category** — the assignable unit a skill grants access to (a group of related tools), not an individual tool. See [[Skill System]], [[Tool Architecture]].

**Turn** — a single user message → agent response cycle. One turn may involve many LLM calls and tool executions. See [[Turn Lifecycle]].

**UDS** — Unix Domain Socket. Used for IPC between the aiohttp app and the broker subprocesses. See [[Credential Brokering]].

**Virtual Computer** — the agent's file system sandbox at `/home/computron` (`virtual_computer.home_dir`). The agent reads, writes, and runs code here via `tools/virtual_computer/`, guarded by a heuristic bash deny-list, not a hard security sandbox. See [[Sandboxed Code Execution]].

**Vault** — the AES-256-GCM encrypted credential store owned by the broker platform. See [[Credential Brokering]].
