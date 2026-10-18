# Glossary

**Agent** — a configured LLM instance with a name, model, system prompt, inference parameters, and a list of callable tools. Constructed by `build_agent()` from an `AgentProfile`. See [[build_agent]].

**AgentEvent** — the event envelope emitted during a turn. Contains a typed payload and agent attribution metadata. Streamed to the UI as JSONL. See [[AgentEvent]], [[Event System]].

**AgentProfile** — a persisted configuration driving one agent: model, provider, system prompt, skills, and inference parameters. What the user creates in the Agents settings tab. See [[AgentProfile]].

**Agent Span** — a hierarchical execution context wrapping one agent's work within a turn. Depth 0 = root agent; depth 1+ = sub-agents. Attributed to all events published during the span. See [[Turn Lifecycle]].

**AppConfig** — the Pydantic model holding the full application configuration, loaded from `config.yaml`. See [[AppConfig]].

**Broker** — a per-integration subprocess (UID 1001) that holds decrypted credentials and connects to upstream services. Communicates with the app via UDS. See [[Integrations Architecture]].

**BudgetGuard** — a hook that enforces `max_iterations` on the agent turn loop.

**Compaction** — the process of summarizing older conversation history when the context window approaches capacity, so the agent can continue without hitting the token limit. See [[Context Compaction]].

**CompactionThreshold** — the fill ratio (0.0–1.0) at which compaction fires. Default 0.75 (75% full). Configurable per AgentProfile.

**Conversation** — a persistent multi-turn exchange between user and agent, identified by a `conversation_id` string. Owns a `ConversationHistory` and `ContextManager`. See [[ConversationHistory]].

**ConversationHistory** — the in-memory ordered list of LLM messages (system, user, assistant, tool) for one conversation. Persisted as `history.json`. See [[ConversationHistory]].

**ContextManager** — tracks token usage for a conversation and fires compaction strategies when fill ratio crosses the threshold. See [[Context Compaction]].

**CSRF** — Cross-Site Request Forgery guard. All mutating API calls require `X-Requested-With: XMLHttpRequest`. Cross-origin JS cannot set this header, so its presence signals a same-origin request. See [[API Routes]].

**EventDispatcher** — per-turn fan-out publisher. Delivers `AgentEvent` objects to all registered subscribers (SSE bridge, event buffer hook). See [[Event System]].

**Goal** / **Routine** — an autonomous task with a name, prompt, schedule, and profile. Executed by the Task Engine without a human in the loop. The UI labels these "Routines". See [[Task Engine]].

**Hook** — a pluggable callback implementing one or more turn phases (`before_model`, `after_tool`, etc.). Hooks compose onto the turn loop without modifying core execution. See [[Hooks System]].

**Integration** — a credentialed connection to an external service (Gmail, iCloud). Runs as an isolated broker subprocess. See [[Integrations Architecture]].

**JSONL** — JSON Lines format: one JSON object per line, used for the SSE event stream from the backend to the frontend.

**Message Group** — one assistant message plus all its immediately-following tool-call results. Compaction never splits a group, preventing orphaned tool results. See [[Context Compaction]].

**Nudge** — a user message injected into a running turn via `POST /api/nudge`. Spliced into history by `NudgeHook` before the next model call, without starting a new turn.

**Profile** — shorthand for [[AgentProfile]].

**Provider** — an LLM inference backend: Ollama (local), OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint. Configured in Settings → Providers.

**Skill** — a reusable named instruction block loaded into a conversation. Skills augment the system prompt and can provide additional tools. Referenced by ID in AgentProfiles.

**Supervisor** — the long-lived process (UID 1001) that owns the credential vault and manages broker subprocesses. See [[Integrations Architecture]].

**TaskRunner** — the background loop that polls for due goals and executes them. Part of the [[Task Engine]].

**Turn** — a single user message → agent response cycle. One turn may involve many LLM calls and tool executions. See [[Turn Lifecycle]].

**UDS** — Unix Domain Socket. Used for IPC between the aiohttp app and the integrations supervisor/brokers.

**Virtual Computer** — the agent's file system sandbox at `/home/computron`. The agent reads, writes, and runs code here via `tools/virtual_computer/`. See [[Tool Architecture]].

**Vault** — the AES-256-GCM encrypted credential store for integrations at `/var/lib/computron/vault/`. Owned by the `broker` OS user. See [[Integrations Architecture]].
