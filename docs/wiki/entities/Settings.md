---
title: Settings
type: entity
tags: [config, settings, runtime]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "settings.py"
---

# Settings

## Overview

Runtime, user-editable application state — distinct from [[AppConfig]] (`config.yaml`),
which is static and set by whoever deploys the container. Settings are what the setup
wizard and the in-app settings page write: default agent, direct-connect provider
endpoints, vision/compaction/title model selection, experimental feature toggles, and
update-notification preferences. Persisted as flat JSON in `settings.json` under the
state home directory.

## Location

`settings.py` (top-level module, not a package).

## Details

`load_settings()` returns the parsed `settings.json` **verbatim** — it deliberately does
not re-merge in `_DEFAULTS` on every read. A brand-new install (no file yet) gets a copy
of `_DEFAULTS`; once `save_settings()` writes the file for the first time, it's seeded
with every default key, and any key later added to `_DEFAULTS` only reaches *new*
installs until a migration backfills it onto existing ones (see `migrations/`).

Key fields in `_DEFAULTS`:

| Key | Purpose |
|-----|---------|
| `setup_complete` | Whether the first-run wizard has finished |
| `default_agent` | Agent profile id used when none is specified |
| `direct_providers` | `{name: {"base_url": ...}}` for direct-connect OpenAI-compatible endpoints. Providers needing an API key live in the brokering vault instead, not here. |
| `vision_provider` / `vision_model` / `vision_think` / `vision_options` | Model used for image-input tasks |
| `compaction_provider` / `compaction_model` / `compaction_options` | Model used for context compaction summarization |
| `title_provider` / `title_model` | Model used for conversation title generation (see [[ConversationHistory]]) |
| `custom_apps_enabled` / `custom_tools_enabled` | Feature flags for experimental subsystems |
| `home_app_slug` | A custom app to show as Home instead of Chat |
| `software_updates_automatic` / `software_updates_notify` | Desktop-app update behavior; ignored when running from the CLI |

`SettingsUpdate` (a Pydantic model with `extra="forbid"`) is the allow-list for a
settings `PUT` request — any key not declared on it is rejected before it can reach
disk. It also validates `home_app_slug` (must match a lowercase slug pattern) and
`direct_providers` (`base_url` must be `http`/`https` and not point at a known cloud
metadata-service IP — `169.254.169.254`, `fd00:ec2::254`,
`metadata.google.internal` — to block a classic SSRF-to-credentials path).

`save_settings(data)` does a read-modify-write: loads the current file (or defaults),
shallow-merges `data` in, and writes atomically via a temp file + `os.replace`.

## Key Functions

- `load_settings()` — read current settings, or defaults if unset
- `save_settings(data)` — merge and persist; returns the full resulting dict
- `custom_apps_enabled()` / `custom_tools_enabled()` — convenience boolean checks

## Related Entities

- [[AppConfig]] — the static counterpart
- [[ConversationHistory]] — title generation reads `title_provider`/`title_model`

## Sources

- None beyond `settings.py`.
