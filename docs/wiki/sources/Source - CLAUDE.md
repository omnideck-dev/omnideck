---
title: "Source - CLAUDE.md"
type: source
tags: [conventions, architecture, python, frontend, testing]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - CLAUDE.md

## Summary

CLAUDE.md is the developer coding conventions reference for Omnideck (internal codename: Computron 9000). It covers Python style rules, module structure principles, testing conventions, and React frontend guidelines. It is the authoritative guide for how the codebase is organized and how code should be written.

## Key Points

- Build system: `just` (Justfile recipes) and `uv` for Python dependency management
- Python 3.12.10, aiohttp backend, React 18 frontend
- No f-strings in logging; use `logger.info("message %s", var)` format
- Module-level loggers (`logger = logging.getLogger(__name__)`)
- `__init__.py` is a pure re-export facade — no implementation code lives there
- Leading-underscore module naming (`_rpc.py`) signals "internal to parent package"
- Symbols inside an internal module only get underscore if module-local; cross-module-used symbols stay unprefixed
- Eager imports by default; lazy imports only for heavy optional deps (playwright, torch, transformers)
- Circular imports are design bugs — fix the graph by extracting a shared leaf module
- Tool functions that the LLM invokes MUST have Google-style docstrings (these serve as LLM documentation)
- No cross-file path references in comments — describe the concept, not the location
- Feature flags: `ENABLE_IMAGE_GEN`, `ENABLE_MUSIC_GEN`, `ENABLE_DESKTOP`, `ENABLE_GROUNDING`, `ENABLE_CUSTOM_TOOLS`
- React frontend: JSX (not TypeScript), Vite for bundling, Vitest for testing, CSS Modules

## Entities Mentioned

- [[AppConfig]]
- [[Settings]]
- [[ContextManager]]
- [[AgentProfile]]
- [[BrowserTool]]
- [[Tool Schema Generation]]

## Concepts Covered

- [[Tool Schema Generation and Dispatch]]
- [[Provider Abstraction]]
- [[Hook System]]

## Raw Notes

- Google-style docstrings are the LLM's documentation for tools — never put implementation details in them
- `just unit` / `just e2e` / `just integration` test targets
- Ruff for linting/formatting, mypy for type checking
- Types live in leaf modules with no internal dependencies to avoid circular imports
- `server/ui/` contains the React frontend with CSS Modules per component
- Dev workflow: `just dev` copies source into container via tar-pipe (no bind mount), `just restart-app` bounces only the Python process
