# Omnideck

A self-hosted agentic workbench in a single container. Bring your own LLMs — securely-brokered cloud providers (OpenAI, Anthropic, OpenRouter, any OpenAI-compatible endpoint) or local Ollama models — and connect the integrations your agents need (Gmail, Calendar, Drive, custom MCP servers). Agents browse the web, write and run code, and work on goals in the background. Everything runs on your hardware.

![Omnideck](image.png)

## Prerequisites

- A container engine: [Docker](https://docs.docker.com/get-docker/) or Podman
- The [`omnideck` CLI](https://github.com/omnideck-dev/cli) — installs and manages Omnideck for you
- An LLM provider — a cloud account (OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint) or [Ollama](https://ollama.com/) for local models

## Install the CLI

The `omnideck` CLI wraps your container engine with a guided installer and simple management commands. This one-liner detects your OS and architecture, downloads the matching binary, and installs it to your path — it works on Linux, macOS, and Windows via [WSL2](https://learn.microsoft.com/windows/wsl/install):

```bash
curl -L -o omnideck "https://github.com/omnideck-dev/cli/releases/latest/download/omnideck-$(uname -s | tr '[:upper:]' '[:lower:]')-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')" \
  && chmod +x omnideck && sudo mv omnideck /usr/local/bin/
```

Prefer to grab it by hand? Binaries for Linux and macOS (`amd64` and `arm64`) are attached to every [release](https://github.com/omnideck-dev/cli/releases/latest).

Verify it's on your path:

```bash
omnideck --version
```

## Get Started

```bash
omnideck install
```

The install wizard detects your container engine, checks that Ollama is reachable, suggests memory limits sized for your machine, and starts the container.

When it finishes, open **[http://localhost:2337](http://localhost:2337)**. A setup wizard walks you through adding an LLM provider and picking your main model (used for chat, compaction, and titles) plus an optional vision model. Cloud providers list their models automatically; Ollama lists whatever you've pulled.

That's it — you're running.

## Managing Omnideck

Everything is driven through the CLI:

```bash
omnideck status      # container, data dirs, Ollama, and web UI port at a glance
omnideck logs -f     # tail container logs
omnideck stop        # gracefully stop the container
omnideck start       # start it back up
omnideck restart     # stop then start
omnideck update      # pull the latest image and recreate the container
omnideck doctor      # run health checks and print a pass/warn/fail report
omnideck uninstall   # remove the container (optionally back up and delete data)
```

Your data lives in `~/Omnideck` and survives restarts and upgrades. Conversations, memory, agent profiles, goals, and generated files are all preserved when you `update`.

Run `omnideck --help` (or `omnideck <command> --help`) for the full list of commands and flags.

## Using Ollama for Local Models

If you'd rather run models locally than use a cloud provider, install [Ollama](https://ollama.com/) on the host and pull at least one model. The setup wizard lists whatever you've pulled.

```bash
ollama pull kimi-k2.5    # main model
ollama pull qwen3.5      # vision model
```

| Role | Suggested | Notes |
|------|-----------|-------|
| Main | `kimi-k2.5` | Also used for compaction (context summarization) and title generation |
| Vision | `qwen3.5` | Must support image input — or use your main model if it does |

**Ollama cloud models** — Ollama can broker cloud-hosted variants alongside your local models so they show up the same way in the app. After `ollama login`, pull a cloud variant:

```bash
ollama pull kimi-k2.5:cloud
```

Cloud variants skip your local GPU but still need to be pulled so Ollama exposes them.

## Features

- **Chat** — talk to the agent, ask it to do things
- **Agent Profiles** — reusable configurations bundling model, system prompt, skills, and inference parameters. Ship with defaults, or create your own in Settings.
- **Browser automation** — controls Chrome with human-like clicking, typing, and scrolling
- **Code execution** — writes and runs Python, installs packages, builds projects
- **Autonomous tasks** — schedule recurring goals that run in the background
- **Memory** — persistent memory across conversations
- **Integrations** — connect Gmail, Calendar, Drive, and custom MCP servers

## Troubleshooting

Start with `omnideck doctor` — it runs parallel health checks (engine, container, Ollama, web UI port) and prints exactly what's wrong and how to fix it.

**UI doesn't load** — Give it 10–15 seconds to start, then check `omnideck logs`.

**"Ollama connection refused"** — Only matters if you're using local models. Make sure Ollama is running on the host; `omnideck doctor` reports reachability. On macOS / Docker Desktop, Ollama must be bound to `0.0.0.0` (set `OLLAMA_HOST=0.0.0.0` and restart it — it defaults to `127.0.0.1`).

## Building from Source

To build the Omnideck container image yourself instead of pulling from the registry:

```bash
git clone https://github.com/omnideck-dev/omnideck
cd omnideck
docker build -f container/Dockerfile -t omnideck:latest .
```

Then point the CLI at your local image:

```bash
omnideck install --image omnideck:latest
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the dev workflow.
