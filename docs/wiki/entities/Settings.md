---
title: Settings
type: entity
tags: [settings, runtime, json, mutable]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Config and Settings]]"]
---

# Settings

## Overview

`settings.py` manages the mutable runtime settings stored in `{home_dir}/settings.json`. Unlike `AppConfig` (static YAML), settings are modified by the setup wizard and the settings UI. They control which LLM providers/models are active, the default agent, and feature configurations.

## Details

**Key settings fields:**
- `setup_complete: bool` — whether the setup wizard has run
- `default_agent: str` — profile ID of the default agent (default: "omnideck")
- `direct_providers: dict` — `{provider_name: {base_url: "..."}}` for Ollama and unauthenticated OpenAI-compatible endpoints; brokered providers (with API keys) live in the vault
- `vision_provider`, `vision_model`, `vision_think`, `vision_options` — for `inspect_page` / `browser_visual_action` / `describe_image`
- `compaction_provider`, `compaction_model`, `compaction_options` — for [[LLMCompactionStrategy]]
- `title_provider`, `title_model` — for conversation title generation

**`load_settings():`** reads disk verbatim; returns `_DEFAULTS` copy if file missing; no re-merge with defaults on miss

**`save_settings(data):`** merges `data` into current settings and writes atomically

**`SettingsUpdate` model:** Pydantic model for PUT requests; `extra="forbid"` rejects unknown keys; validates `direct_providers` base URLs (must be http/https, not cloud metadata endpoints)

**Security — SSRF protection:**
- `_BLOCKED_HOSTS = {"169.254.169.254", "fd00:ec2::254", "metadata.google.internal"}`
- Direct provider base_url must pass `_validate_base_url()` check

**Defaults vs migrations:**
- `_DEFAULTS` is baked into settings.json on first write
- Missing keys on old installs are NOT silently filled from defaults — migrations close those gaps

## Related Entities

- [[AppConfig]] (static, immutable counterpart)
- [[LLMCompactionStrategy]] (reads compaction settings)
- [[OllamaProvider]] (reads direct_providers)
- [[AgentProfile]] (get_default_profile reads `default_agent`)
- [[BrowserTool]] (reads vision settings)

## Sources

- [[Source - Config and Settings]]
