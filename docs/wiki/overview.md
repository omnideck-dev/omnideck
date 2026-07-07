# Overview

## What is Omnideck?

Omnideck is a self-hosted agentic workbench that runs as a single container. Users bring their own LLMs — local via Ollama or cloud-hosted (OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint) — and connect integrations (Gmail, Google Calendar, custom MCP servers). The agent can browse the web with a full Chromium instance, write and run code in a sandboxed virtual computer, and execute autonomous background tasks (goals/routines) on a schedule.

The system is designed to run on user hardware with full data ownership: conversations, memory, agent profiles, and generated files all live in `~/Omnideck` on the host and survive container restarts and upgrades.

## Architecture in one diagram

```
Browser (React UI)
      │  SSE (JSONL event stream)
      ▼
aiohttp server :8080
      │
      ├── server/message_handler.py  ← chat request entry point
      │          │
      │          ├── agents/          ← load AgentProfile → build Agent
      │          ├── sdk/turn/        ← run_turn() → LLM provider loop
      │          ├── sdk/hooks/       ← persistence, context, loop detection, budget
      │          ├── sdk/events/      ← EventDispatcher → SSE to UI
      │          └── tools/           ← browser, virtual_computer, memory, integrations...
      │
      ├── tasks/                      ← autonomous background task engine
      ├── conversations/              ← history + event persistence
      ├── integrations/               ← supervisor + brokers (email, calendar)
      └── migrations/                 ← one-time data migrations on startup

Host: Ollama :11434 (local LLM inference, accessed via --network=host)
Container: Chromium + Xfce desktop (VNC :5900), GPU inference server
```

## Key concepts

**AgentProfile** — a saved configuration: model, system prompt, skills, inference parameters, and tool settings. Profiles drive both chat sessions and autonomous tasks.

**Turn** — one user message → agent response cycle. The SDK's `run_turn()` drives the LLM in a loop (call → tool executions → call) until the model stops issuing tool calls or a stop condition fires. Hooks observe and can modify each phase.

**Events** — a discriminated-union stream of typed payloads (`ContentPayload`, `ToolCallPayload`, `BrowserScreenshotPayload`, `FileOutputPayload`, etc.) flowing from the agent loop to the frontend via Server-Sent Events.

**Integrations** — credentialed external services (Gmail, iCloud) running as isolated broker subprocesses under a separate OS user, with AES-256-GCM encrypted credentials and a write-permission gate.

**Virtual Computer** — a directory on disk (`/home/computron`) that the agent reads, writes, and executes code in via sandboxed bash commands.

**Skills** — reusable named instruction blocks the user or agent can load into a conversation, augmenting the system prompt mid-turn.

**Goals / Routines** — autonomous tasks defined by name, prompt, schedule, and profile. The `TaskRunner` polls pending goals and dispatches them through the same SDK turn loop, without a human in the loop.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, aiohttp, Pydantic v2, uv |
| Frontend | React 18 (JSX), Vite, Vitest, CSS Modules |
| Container | Podman / Docker; single image with Xfce desktop + Chromium |
| LLM inference | Ollama (host) or cloud providers via HTTP |
| Testing | pytest (unit/integration), Playwright (e2e) |
| Config | `config.yaml` with `${ENV_VAR:-default}` interpolation |

## Where to go next

- [[codemap]] — file-by-file navigation
- [[Turn Lifecycle]] — how a chat message becomes a model response
- [[Event System]] — how the agent communicates with the UI
- [[Integrations Architecture]] — how external service credentials and brokers work
- [[AgentProfile]] — what drives an agent's behavior
- [[Frontend Architecture]] — React component structure and data flow
