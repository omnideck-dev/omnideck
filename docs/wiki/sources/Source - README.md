---
title: "Source - README.md"
type: source
tags: [readme, overview, installation, features]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - README.md

## Summary

The Omnideck README describes a self-hosted agentic workbench that runs as a single container. Users bring their own LLMs (cloud or local via Ollama) and connect integrations (Gmail, Calendar, Drive, custom MCP servers). The system is installed and managed via the `omnideck` CLI (a separate Go binary), and provides a web UI at port 2337 (production) or 8080 (dev). All data persists in `~/Omnideck` on the host.

## Key Points

- Single-container architecture: app server, desktop environment (Xfce+VNC), browser (Chrome), and GPU inference all in one image
- LLM inference via Ollama on host (accessed through `--network=host`) or brokered cloud providers
- Managed by the `omnideck` CLI: install, start, stop, restart, update, doctor, uninstall, logs, status
- Web UI at `http://localhost:2337` after install; setup wizard configures LLM provider and main model
- Supports OpenAI, Anthropic, OpenRouter, any OpenAI-compatible endpoint, and local Ollama models
- Agent profiles bundle model, system prompt, skills, and inference parameters; default profiles ship with the app
- Data stored in `~/Omnideck`; persists across container restarts and updates
- Feature: browser automation (Chrome via Playwright), code execution (Python), autonomous background tasks, persistent memory, integrations (Gmail, Calendar, Drive, MCP)
- For local models: `kimi-k2.5` recommended for main/compaction/title; `qwen3.5` for vision
- Ollama cloud variants (`kimi-k2.5:cloud`) allow cloud-brokered models via Ollama interface
- `omnideck doctor` runs parallel health checks and reports pass/warn/fail

## Entities Mentioned

- [[AgentProfile]]
- [[BrowserTool]]
- [[MemoryTool]]
- [[TaskRunner]]
- [[IntegrationSupervisor]]
- [[OllamaProvider]]
- [[AnthropicProvider]]
- [[OpenAIProvider]]
- [[OpenRouterProvider]]

## Concepts Covered

- [[Agent Loop]]
- [[Context Compaction]]
- [[Skill System]]
- [[Integration Supervisor and Broker Pattern]]
- [[Browser Automation]]

## Raw Notes

- Internal codename is "Computron 9000" (referenced in CLAUDE.md and DEVELOPMENT.md)
- Container image: `ghcr.io/omnideck-dev/omnideck:main`
- Port 2337 is the public port, but internally the aiohttp server runs on 8080
- Setup wizard required on first run; selects provider/model, stamps profiles
- The CLI (`omnideck`) is a separate Go binary in a separate repository
