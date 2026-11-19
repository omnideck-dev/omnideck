# Overview

## What is Omnideck?

Omnideck is a self-hosted agentic workbench that runs as a single container. Users bring their own LLMs — local via Ollama or cloud-hosted (OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint) — and connect integrations (Gmail, Google Calendar, custom MCP servers on the roadmap). The agent can browse the web with a full Chromium instance, write and run code in a sandboxed virtual computer, spawn sub-agents, and execute autonomous background routines on a schedule.

The system is designed to run on user hardware with full data ownership: conversations, memory, agent profiles, and generated files all live in `~/Omnideck` on the host (bind-mounted into the container) and survive container restarts and upgrades.

## Architecture in one diagram

```
Browser (React UI, feature-folder architecture)
      │  SSE (resumable JSONL event stream, run_id/seq cursor)
      ▼
aiohttp server :8080 (or :2337 via the CLI)
      │
      ├── server/_agent_run_routes.py   ← chat/run request entry point
      │          │
      │          ├── agents/            ← AgentProfile → agent_runtime.build_agent()
      │          ├── agent_runtime/     ← AgentRuntime → RunSession → AgentRunner, sub-agent spawn, compaction
      │          ├── agent_core/        ← turn loop, hooks, events, context/history, provider protocol, skills, tool schema
      │          └── tools/             ← browser, virtual_computer, memory, integrations, custom_tools, desktop, web...
      │
      ├── tasks/                        ← autonomous Routine engine (Routine → Run → Task DAG)
      ├── conversations/                ← event-log persistence, metadata, folders
      ├── artifacts/                    ← generated-file index
      ├── integrations/ + brokering/    ← tool-integration catalog + credential-broker subprocesses
      └── migrations/                   ← one-time data migrations on startup

Host: Ollama :11434 (local LLM inference, accessed via --network=host)
Container: Chromium + Xfce desktop (VNC :5900), GPU inference server
```

`sdk/` — the package the previous version of this wiki documented as the core — is now dead code: every subpackage is empty and nothing imports from it. `agent_core/` (per-turn primitives) and `agent_runtime/` (session/run orchestration) replaced it entirely. See [[WIKI-PROMPT]] for how this wiki stays current as the codebase keeps moving.

## Key concepts

**AgentProfile** — a saved configuration: model, system prompt, skills, inference parameters, and tool settings. Profiles drive both chat sessions and autonomous routines.

**Turn** — one user message → agent response cycle. `agent_runtime.AgentRunner` drives the LLM in a loop (call → tool executions → call) through `agent_core`'s turn primitives, until the model stops issuing tool calls or a stop condition fires. Hooks observe and can modify each phase.

**Events** — a discriminated-union stream of typed payloads flowing from the agent loop to the frontend via Server-Sent Events, replayable by `run_id`/`seq` cursor for resume.

**Sub-agents** — an agent can spawn sub-agents (`agent_runtime/_spawn.py`) to handle subtasks, each with hierarchical execution-id attribution and its own profile/context.

**Integrations & Brokering** — credentialed external services (Gmail, iCloud) and model-provider connections run through isolated broker subprocesses with AES-256-GCM encrypted credentials; `integrations/` is the application-level catalog/grants layer, `brokering/` is the vault/subprocess platform underneath it.

**Virtual Computer** — a directory on disk (`/home/computron`) that the agent reads, writes, and executes code in via sandboxed bash commands — a heuristic deny-list, not a hard security sandbox.

**Skills** — reusable, stored capability bundles (`skills/`) the user or agent can load into a conversation (`agent_core/skills/`), augmenting the system prompt and granting tool categories mid-conversation.

**Routines** — autonomous tasks (formerly "Goals") defined by name, prompt, schedule, and profile, structured as a DAG of tasks within a run. The Task Engine polls for due routines and dispatches them through `AgentRuntime`, without a human in the loop.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, aiohttp, Pydantic v2, uv |
| Frontend | React 18 (JSX + generated TypeScript event types), Vite, Vitest, CSS Modules |
| Container | Podman / Docker; single image with Xfce desktop + Chromium |
| LLM inference | Ollama (host) or cloud providers via HTTP, brokered through `brokering/`'s `llm_proxy` |
| Testing | pytest (unit/integration), Playwright (e2e) |
| Config | `config.yaml` (static startup) + `settings.json` (runtime-editable) |

## Where to go next

- [[codemap]] — file-by-file navigation
- [[Turn Lifecycle]] — how a chat message becomes a model response
- [[Event System]] — how the agent communicates with the UI
- [[Multi-Agent Architecture]] — how sub-agents are spawned and attributed
- [[Integrations Architecture]] and [[Credential Brokering]] — how external credentials and brokers work
- [[AgentProfile]] — what drives an agent's behavior
- [[Frontend Architecture]] — React component structure and data flow
- [[Using Omnideck at Work]] — the non-code-mapped guide for IT/security review questions
