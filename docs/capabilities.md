# Omnideck — Core Capabilities

*For marketing and sales. Describes shipped, working capabilities only — roadmap items are called out separately at the bottom, not mixed in above.*

## What it is

Omnideck is a self-hosted AI agent workbench that runs in a single container on the customer's own hardware. It's not a chatbot wrapper — it's a platform for building agents that can browse the web, control a computer, run code, connect to real accounts (email, calendar, files), remember context over time, and act on a schedule without anyone watching. Everything — data, credentials, execution — stays on the customer's machine. No Omnideck account, no telemetry, no vendor lock-in on the model (bring any LLM).

The pitch in one line: **give people a private, extensible workbench where they assemble their own agents out of real capabilities, instead of asking them to trust a hosted black box.**

---

## 1. Talk to it, and it does things — not just answers

The core experience is chat, but the agent isn't limited to text back. It can browse, click, type, run code, touch files, and call real integrations mid-conversation to get something done, with the results (and reasoning) visible in the UI as it works.

## 2. Any LLM, your choice — no vendor lock-in

Works with OpenAI, Anthropic, OpenRouter, any OpenAI-compatible endpoint, or fully local models via Ollama. Model choice is assigned **per role** — the model doing chat, the one doing vision, and the one doing conversation summarization can each be a different provider. Nothing is hard-wired to one vendor, including running 100% offline on local models with no external API calls at all.

## 3. It can operate a real computer, not just answer questions

- **Browser control** — drives an actual Chrome browser: clicking, typing, scrolling, filling forms, navigating multi-page flows, and extracting information from pages, the same way a person would.
- **Full desktop control** — beyond the browser, it can operate a virtual desktop directly: mouse and keyboard actions against any on-screen application, reading what's on screen (fast structural read, or a full visual description via a vision model).
- **Sandboxed code execution** — writes and runs code (shell, Python, etc.), installs packages, reads/writes/searches/patches files, in an isolated environment inside the container. Real software work, not a toy REPL.
- **Image and music generation** — generates images and full original songs (including vocals) with live streaming preview in the UI, as a first-class tool the agent can call.

## 4. Connects to the accounts people actually use

Gmail, Google Calendar, Google Drive/Contacts, and generic HTTP APIs today. Integrations are explicit and named — an agent never quietly acts on an account it wasn't told to use. Credentials are encrypted at rest and only ever decrypted inside an isolated broker process; the agent's own runtime never sees raw credentials. Practically: an agent can read and draft email, manage a calendar, pull files from Drive, or call a customer's own internal APIs, without the customer handing raw secrets to a model.

## 5. Remembers — across conversations, not just within one

Persistent memory carries facts, preferences, and project context forward between sessions, alongside searchable, foldered conversation history. An agent that helped last week still knows what it learned then.

## 6. Works while nobody's watching

**Routines** turn any agent capability into a scheduled, recurring background job (cron-based, timezone-aware) — check something every morning, monitor a feed, run a nightly digest, follow up on a task automatically. The agent works on its own time, not just when someone's typing.

## 7. Build your own solutions — this is the core differentiator

Omnideck isn't a fixed set of features; it's building blocks people assemble into their own agent, tool, or workflow:

- **Custom Tools** — write a tool (a shell command or a full Python/Bash script) once, and the agent can call it forever after, no restart needed. This is how a customer turns "the thing I do by hand every day" into something the agent just does.
- **Custom Agent Profiles** — bundle a model, system prompt, skills, and inference parameters into a reusable profile. Ships with ready-made profiles (general orchestrator, code expert, creative writer, researcher) as starting points, but any profile can be built from scratch.
- **Skills** — composable capability packages that can be loaded mid-conversation, mixed and matched, multiple active at once on a single agent. Add capability without rebuilding the agent.
- **Sub-agent orchestration** — an agent can spawn sub-agents to divide up work, and those can spawn further sub-agents, arbitrarily nested, each with its own profile and context. This is how a customer builds a real multi-agent pipeline (e.g., one agent researches, another writes, another verifies) instead of one model doing everything badly.
- **Multiple isolated instances** — separate Omnideck instances for work, home, or individual projects, each with its own agents, configuration, and integration access, with no data crossing between them.
- **Packs** — export a profile plus its skills as a single portable bundle and share it with a teammate or another install. Solutions built once don't have to be rebuilt.

Put together, these are the pieces of a pitch like: *"build an inbox agent that triages email every morning, drafts replies in your voice, and pings you only when it needs a decision — using tools and data you already own."*

## 8. Self-hosted, private by construction

- **Zero telemetry** — no analytics SDKs, no crash reporters, no update-check calls. The only network traffic is what the customer explicitly triggers: calls to their chosen LLM provider, or their own integrations.
- **Data stays local** — conversations, memory, and files live on the customer's own machine, survive restarts and upgrades.
- **No account required** — no Omnideck login or registration. The only account needed is with whichever LLM provider is chosen, and even that disappears when running local models.
- **Sandboxed execution** — the agent runtime runs inside a container with restricted host access; credentials are encrypted at rest (AES-256-GCM) and only ever touched inside isolated broker processes, never by the agent itself.
- **Open source** — Apache 2.0 licensed.

## 9. Easy to get running

Ships two ways: a desktop application (Windows, macOS, Linux) that sets up its own container runtime automatically with no command-line knowledge required, and a CLI (`omnideck`, installable via Homebrew) for people who want direct control. Either way, it's one container image, running on hardware the customer already owns.

---

## What's next (roadmap — not yet shipped, don't sell as current)

- **MCP server support** — connecting Omnideck to the broader Model Context Protocol ecosystem.
- **Workflows** — an evolution of Routines into multi-step, conditional, chained automations (Routines themselves are shipped and working today; this is about making them composable).
- **Custom Apps** — an early/experimental workspace runtime that lets a user build their own small app (backend actions + frontend) inside Omnideck. It exists and functions today but is still labeled experimental in the code — worth a mention as "in active development," not as a finished pillar feature yet.
