---
title: AppConfig
type: entity
tags: [config, infra]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "config/__init__.py"
  - "config.yaml"
---

# AppConfig

## Overview

`AppConfig` is the Pydantic model for static, deployment-level configuration: loaded
once from `config.yaml` via `load_config()` and cached with `@lru_cache(maxsize=1)`.
It's distinct from [[Settings]] (`settings.py`), which holds mutable, user-editable
runtime state in `settings.json` — `AppConfig` is what the person who deployed the
container controls; `Settings` is what the user changes from inside the running app.

## Location

Defined in `config/__init__.py`. Config file: `config.yaml` (repo root).

## Details

`AppConfig` is composed of nested sub-models:

| Sub-model | Field | Key settings |
|-----------|-------|--------------|
| `Settings` | `settings` | `home_dir` — state directory path (expanded on validation) |
| `VirtualComputerConfig` | `virtual_computer` | `home_dir` — agent workspace path |
| `FeaturesConfig` | `features` | `image_generation`, `music_generation`, `desktop`, `visual_grounding` (booleans; note: `custom_tools`/`custom_apps` enablement moved to [[Settings]], not here) |
| `ToolsConfig` | `tools` | `browser` (nested `BrowserToolsConfig`) |
| `BrowserToolsConfig` | `tools.browser` | `headless`, `human` (typing/pointer simulation timing), `waits` (`BrowserWaitConfig`), `scroll_warn_threshold`, `scroll_hard_limit`, `max_open_tabs` |
| `BrowserWaitConfig` | `tools.browser.waits` | Load/font/DOM-mutation/animation timeout tuning, incl. `post_action_nav_grace_ms` — a grace window for navigations some sites fire a beat after a click returns |
| `DesktopConfig` | `desktop` | `user_display`, `agent_display_base`, `resolution`, `websocket_port` — noVNC + Xfce4 |
| `ParallelConfig` | `parallel` | `enabled`, `max_concurrent` for sub-agent spawning |
| `RoutinesConfig` | `routines` | `enabled`, `routines_dir`, `poll_interval`, `max_concurrent`, `shutdown_timeout`, `timezone`, `notifications` (`NotificationsConfig`) — renamed from `GoalsConfig`, see [[Task Engine]] |
| `IntegrationsConfig` | `integrations` | `app_sock_path`, `sockets_dir` — Unix socket paths for the brokering supervisor/brokers |

### `config.yaml` format

Values use `${ENV_VAR:-default}` syntax for env-var interpolation. `_resolve_env_vars`
walks the parsed YAML tree and substitutes before Pydantic validation; resolved string
values are parsed back into bool/int/float where they look like one
(`_parse_yaml_scalar`). An env var reference with no `:-` default (`${VAR}`) resolves
to `None` if unset; one with an explicit empty default (`${VAR:-}`) resolves to `""`.

```yaml
features:
  desktop: ${ENABLE_DESKTOP:-false}
  image_generation: ${ENABLE_IMAGE_GEN:-false}
```

A `.env` file is loaded (via `python-dotenv`) at import time, before any config is
read, so env-driven defaults resolve correctly even if another module imports `config`
first.

## Key Function

```python
from config import load_config

cfg = load_config()  # cached; call freely
```

## Related Entities

- [[Settings]] — the mutable counterpart (`settings.json`), for state the user changes at runtime
- [[AgentProfile]] — per-agent configuration layered on top of `AppConfig`
- [[Task Engine]] — reads `RoutinesConfig`

## Sources

- None beyond `config/__init__.py` and `config.yaml`.
