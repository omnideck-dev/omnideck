<p align="center">
  <a href="https://omnideck.dev">
    <img src="image.png" alt="Omnideck" width="600"/>
  </a>
</p>

<h1 align="center">Omnideck</h1>

<p align="center">
  <strong>A self-hosted AI agent workbench in a single container. Bring your own LLMs, connect your integrations, and run agents on your own hardware.</strong>
</p>

<p align="center">
  <a href="https://github.com/omnideck-dev/omnideck/releases">
    <img src="https://img.shields.io/github/v/release/omnideck-dev/omnideck?include_prereleases&style=flat-square&label=release" alt="Latest Release">
  </a>
  <a href="https://github.com/omnideck-dev/omnideck/actions/workflows/publish.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/omnideck-dev/omnideck/publish.yml?branch=main&style=flat-square&label=CI" alt="CI Status">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square" alt="License: Apache 2.0">
  </a>
  <a href="https://omnideckcommunity.slack.com/">
    <img src="https://img.shields.io/badge/Slack-Join%20us-4A154B?style=flat-square&logo=slack&logoColor=white" alt="Slack">
  </a>
  <a href="https://github.com/omnideck-dev/omnideck/stargazers">
    <img src="https://img.shields.io/github/stars/omnideck-dev/omnideck?style=flat-square" alt="GitHub Stars">
  </a>
</p>

---

## Quick Start

Download the experimental omnideck application for Windows, macOS, or Linux
from the [releases page](https://github.com/omnideck-dev/omnideck/releases).
Install it, open **omnideck**, and follow the guided setup. The application
prepares the shared Omnideck runtime automatically; no container or command-line
knowledge is required.

Prefer the CLI workflow?

```bash
# Install the CLI
brew install omnideck-dev/tap/omnideck

# First use detects and prepares everything automatically
omnideck

# Open the UI in your browser
# → http://localhost:2337
```

---

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Managing Omnideck](#managing-omnideck)
- [Using Ollama for Local Models](#using-ollama-for-local-models)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [Roadmap](#roadmap)
- [Community & Support](#community--support)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Chat** — Talk to the agent, ask it to do things. Conversations include persistent memory across sessions.
- **Agent profiles** — Reusable profiles bundling model, system prompt, skills, and inference parameters. Ships with defaults, or create your own.
- **Multi-provider model support** — Use OpenAI, Anthropic, OpenRouter, any OpenAI-compatible endpoint, or local Ollama models. Model assignment is per-role (chat, vision, compaction can each use a different provider). No provider is privileged over another.
- **Skills** — Loadable capability packages that extend what an agent can do. Skills can be loaded mid-conversation without restarting, and multiple skills can be active simultaneously on a single agent.
- **Sub-agent orchestration** — Agents can spawn sub-agents to handle subtasks, each with its own profile and context. Sub-agents can nest arbitrarily, and execution is tracked via hierarchical agent-span IDs.
- **Multi-agent instances** — Build separate instanes for work, home, and projects — each is its own isolated context with its own agents, configs, and tool access. Agents in one instance don't see data from another.
- **Browser automation** — Controls Chrome with human-like clicking, typing, and scrolling. Agents can browse the web, fill forms, and extract information. 
- **Code execution** — Writes and runs Python, installs packages, builds projects. Full sandboxed code environment inside the container.
- **Routines** — Schedule recurring tasks that run in the background on a cron-like schedule. Agents work while you're away. 
- **Memory** — Persistent memory across conversations. Agents remember facts, preferences, and project context.
- **Integrations** — Connect Gmail, Calendar, Drive, Contacts, and HTTP APIs. Integrations are named and explicit — the agent never acts on an integration without being told which one to use. MCP server support is on the roadmap.

**Privacy:** Zero telemetry — no analytics SDKs, no reporting calls, no update-check endpoints, no crash reporters. The only network traffic is what you explicitly initiate: API calls to your LLM provider or your own integration calls. Everything runs on your machine. Your data stays in `~/Omnideck`.

**Security:** Credentials are encrypted at rest with AES-256-GCM and decrypted only inside isolated broker processes. The agent runtime cannot directly access stored credentials. Agent processes run inside a container with restricted access to the host system.

**No account required:** No Omnideck account, no registration, no login. The only account you need is with your LLM provider... and that disappears entirely if running local models.

---

## Prerequisites

- **omnideck application:** Windows 11, macOS, or a supported desktop Linux
  distribution on x64 or ARM64. Guided setup prepares Podman for that operating
  system and architecture.
- **CLI installs:** [Podman](https://podman.io/) is the one supported container runtime. On first use, the CLI can install or prepare it through the same backend as the desktop app.
- **LLM provider:** An API key for OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint — or [Ollama](https://ollama.com/) for local models.
- **RAM:** 4 GB minimum (8 GB recommended for local models).

---

## Installation

### omnideck application (experimental)

Download the installer for your operating system from the
[omnideck releases](https://github.com/omnideck-dev/omnideck/releases):

| Platform | Installer |
|----------|-----------|
| Windows 11 x64 or ARM64 | `.exe` |
| Apple Silicon or Intel macOS | `.dmg` |
| Ubuntu, Debian, or Linux Mint x64 or ARM64 | `.deb` |
| Fedora, RHEL, Rocky Linux, AlmaLinux, or openSUSE x64 or ARM64 | `.rpm` |
| Other supported desktop Linux x64 or ARM64 | `.AppImage` |

Open the installed application and select **Set up omnideck**. First setup can
take several minutes and might display a normal operating-system permission
prompt. It downloads the application image pinned to that omnideck release, so
an internet connection is required. The setup screen includes Agent Dash while
the runtime is prepared.

### CLI installation

### Step 1: Install the CLI

The `omnideck` CLI prepares Podman with the same guided backend as Desktop and provides simple management commands.

**Option A: Homebrew (macOS and Linux — recommended)**

```bash
brew install omnideck-dev/tap/omnideck
```

To upgrade later:

```bash
brew upgrade omnideck
```

**Option B: Download a binary**

Grab the binary for your OS from the [releases page](https://github.com/omnideck-dev/cli/releases/latest):

| Platform | File |
|----------|------|
| macOS (Apple Silicon) | `omnideck-darwin-arm64.tar.gz` |
| macOS (Intel) | `omnideck-darwin-amd64.tar.gz` |
| Linux (x86-64) | `omnideck-linux-amd64.tar.gz` |
| Linux (ARM64) | `omnideck-linux-arm64.tar.gz` |
| Windows (x86-64) | `omnideck-windows-amd64.zip` |
| Windows (ARM64) | `omnideck-windows-arm64.zip` |

Extract the archive and move the binary to a directory on your PATH. On Linux or macOS:

```bash
tar -xzf omnideck-linux-amd64.tar.gz
chmod +x omnideck
sudo mv omnideck /usr/local/bin/
```

**Verify the install:**

```bash
omnideck --version
```

### Step 2: Install Omnideck

```bash
omnideck
```

The install wizard:

- Detects, installs, or repairs Podman for the current operating system
- Checks whether Ollama is reachable on the host
- Suggests container memory limits sized for your system
- Pulls the container image and starts the container

### Step 3: Open the tool

When the wizard finishes, open **[http://localhost:2337](http://localhost:2337)** in your browser.

A setup wizard runs in the UI the first time you open it. It guides you through:

- **Adding an LLM provider** — cloud (OpenAI, Anthropic, OpenRouter, or any OpenAI-compatible endpoint) or local Ollama
- **Picking your main model** — used for chat, context compaction, and conversation titles
- **Picking an optional vision model** — for tasks that involve image input

Cloud providers list available models automatically. Ollama lists whatever you've already pulled.

That's it — you're running.

---



## Managing Omnideck

All management is driven through the CLI:

```bash
omnideck tui         # open the TUI dashboard to manage your instances
omnideck update      # pull the latest image and recreate the container
omnideck stop        # gracefully stop the container
omnideck start       # start it back up
omnideck restart     # stop then start
omnideck logs -f     # tail container logs
omnideck doctor      # run health checks and print a pass/warn/fail report
omnideck status      # container state, data dirs, Ollama reachability, and web UI port
omnideck uninstall   # remove the container (optionally back up and delete data)
```

Your data lives in a named volume and survives restarts and upgrades. Conversations, memory, agent profiles, routines, and generated files are all preserved when you `update`.

Run `omnideck --help` (or `omnideck <command> --help`) for the full list of commands and flags.

---

## Using Ollama for Local Models

If you'd rather run models locally than use a cloud provider, install [Ollama](https://ollama.com/) (or other local LLM manager) on the host and pull at least one model. The setup wizard lists whatever you've pulled.

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

---

## Troubleshooting

Start with `omnideck doctor` — it runs parallel health checks (engine, container, Ollama, web UI port) and prints exactly what's wrong and how to fix it.

**UI doesn't load** — Give it 10–15 seconds to start, then check `omnideck logs`.

**"Ollama connection refused"** — Only matters if you're using local models. Make sure Ollama is running on the host; `omnideck doctor` checks reachability both from the computer and from the Omnideck container and reports the next step.

---

## Documentation

Full documentation is available at **[omnideck.dev](https://omnideck.dev)**:

- [Getting Started](https://omnideck.dev) — Install and run in under five minutes
- [CLI Reference](https://omnideck.dev) — Full command and flag reference
- [Local Models](https://omnideck.dev) — Run Omnideck fully offline with Ollama
- [Integrations](https://omnideck.dev) — Connect Gmail, Calendar, and Drive
- [Agents](https://omnideck.dev) — Create and customize agent profiles
- [Routines](https://omnideck.dev) — Schedule background tasks

<details>
<summary>Build from source</summary>

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

</details>

---

## Roadmap

- **MCP server support** — Connect custom MCP servers as integrations
- **Workflows** — Multi-step, conditional, and chained agent execution (an evolution of Routines)

See the [project roadmap](https://github.com/omnideck-dev/omnideck/projects) for the full list.

---

## Community & Support

- **Slack** — [Join our community](https://omnideckcommunity.slack.com/) for real-time chat and support
- **GitHub Issues** — [Report bugs](https://github.com/omnideck-dev/omnideck/issues) and request features
- **GitHub Discussions** — [Ask questions](https://github.com/omnideck-dev/omnideck/discussions) and share ideas

### Security

Found a security vulnerability? Please **do not** open a public issue. Email **security@omnideck.dev** instead. See [SECURITY.md](SECURITY.md) for details.

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Setting up a development environment
- Running tests
- Submitting pull requests
- Commit message conventions

---

## License

Omnideck is open-source software licensed under the [Apache License 2.0](LICENSE). Fork it, modify it, use it commercially — no strings attached.
