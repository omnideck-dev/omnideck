---
title: "Source - Config and Settings"
type: source
tags: [config, settings, yaml, environment, feature-flags]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Config and Settings

## Summary

Omnideck separates static configuration (YAML + environment variables, loaded at startup) from mutable runtime settings (JSON, written by the setup wizard and settings UI). `config.yaml` uses `${ENV_VAR:-default}` syntax; `load_config()` resolves these at load time and caches the result. `settings.json` is loaded fresh on every call and represents user-selected state like provider, model, and setup completion.

## Key Points

**AppConfig (`config/__init__.py`):**
- `load_config()` — LRU-cached singleton, loads from `config.yaml`
- `${ENV_VAR:-default}` syntax in YAML; resolved before Pydantic validation
- Top-level sections: `settings`, `virtual_computer`, `features`, `tools`, `desktop`, `parallel`, `goals`, `integrations`
- `Settings.home_dir` — the app's state directory (conversations, profiles, memory, etc.)
- `VirtualComputerConfig.home_dir` — the agent's working directory
- `FeaturesConfig` — boolean flags: `image_generation`, `music_generation`, `desktop`, `visual_grounding`, `custom_tools`
- `GoalsConfig` — task engine config: `enabled`, `poll_interval`, `max_concurrent`, `shutdown_timeout`, `timezone`, `notifications`
- `IntegrationsConfig` — `app_sock_path`, `sockets_dir` for supervisor/broker UDS communication
- `BrowserToolsConfig` — `headless`, `human` (typing/pointer timing), `waits`, `scroll_warn_threshold`, `scroll_hard_limit`, `max_open_tabs`
- `ParallelConfig` — `enabled`, `max_concurrent` for parallel tool execution

**settings.py (runtime settings):**
- `load_settings()` — loads `settings.json` from `{home_dir}/settings.json`, returns `_DEFAULTS` if file missing
- `save_settings(data)` — merges data and writes atomically (temp file + rename)
- `SettingsUpdate` — Pydantic model for PUT requests; `extra="forbid"` rejects unknown keys
- Key fields: `setup_complete`, `default_agent`, `direct_providers`, `vision_provider/model/options`, `compaction_provider/model/options`, `title_provider/model`
- `direct_providers` are provider configs with base_url (for Ollama and unauthenticated OpenAI-compatible); brokered providers (with API keys) live in the vault, not here
- Security: `_BLOCKED_HOSTS` blocks SSRF to cloud metadata services (169.254.169.254, etc.)
- `_DEFAULTS` baked into settings.json on first write; old installs need migrations to get new keys

## Entities Mentioned

- [[AppConfig]]
- [[Settings]]
- [[GoalsConfig]]
- [[IntegrationsConfig]]
- [[BrowserTool]]
- [[TaskRunner]]

## Concepts Covered

- [[Provider Abstraction]]
- [[Context Compaction]]
- [[Sandboxed Code Execution]]

## Raw Notes

- `load_config()` is decorated with `@lru_cache(maxsize=1)` — config is immutable after startup
- `load_settings()` reads from disk every call — it is mutable state
- `_resolve_env_vars()` walks the YAML tree recursively; YAML booleans ("true"/"false"/"yes"/"no") are normalized to Python bools
- `SettingsUpdate.direct_providers` validator calls `_validate_base_url` to reject non-http(s) URLs and cloud metadata endpoints
- Migrations (`migrations/`) close gaps between `_DEFAULTS` and old settings files on upgrade
