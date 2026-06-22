---
title: AppConfig
type: entity
tags: [config, yaml, pydantic, settings]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Config and Settings]]"]
---

# AppConfig

## Overview

`AppConfig` (in `config/__init__.py`) is the Pydantic model loaded from `config.yaml` at startup. It is immutable after loading (LRU-cached singleton via `@lru_cache(maxsize=1)`). Values in the YAML file use `${ENV_VAR:-default}` syntax that is resolved against the environment before Pydantic validation.

## Details

**Top-level sections:**

| Section | Model | Key fields |
|---------|-------|-----------|
| `settings` | `Settings` | `home_dir` — app state directory |
| `virtual_computer` | `VirtualComputerConfig` | `home_dir` — agent workspace |
| `features` | `FeaturesConfig` | `image_generation`, `music_generation`, `desktop`, `visual_grounding`, `custom_tools` |
| `tools` | `ToolsConfig` | `browser` (typing/pointer/wait/scroll config) |
| `desktop` | `DesktopConfig` | `user_display`, `resolution`, `websocket_port` |
| `parallel` | `ParallelConfig` | `enabled`, `max_concurrent` |
| `goals` | `GoalsConfig` | `enabled`, `poll_interval`, `max_concurrent`, `shutdown_timeout`, `timezone` |
| `integrations` | `IntegrationsConfig` | `app_sock_path`, `sockets_dir` |

**`load_config()` behavior:**
1. Opens `config.yaml` (relative to the `config/` directory)
2. `_resolve_env_vars()` recursively replaces `${VAR:-default}` patterns
3. Parsed YAML booleans ("true"/"false") are converted to Python bools
4. Pydantic validates the resolved dict → `AppConfig`
5. Cached; subsequent calls return the same instance

**`Settings.home_dir`:** path-expanded via `Path.expanduser()`; contains conversations, profiles, memory, settings.json

**`VirtualComputerConfig.home_dir`:** the agent's working directory inside the container; files written here are accessible via the file-serving route

## Related Entities

- [[Settings]] (runtime mutable counterpart)
- [[GoalsConfig]] (used by [[TaskRunner]])
- [[IntegrationsConfig]] (used by [[IntegrationSupervisor]])
- [[BrowserTool]] (reads `tools.browser` config)
- [[run_bash_cmd]] (reads `virtual_computer.home_dir`)

## Sources

- [[Source - Config and Settings]]
