---
title: AppConfig
type: entity
tags: [config, settings]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "config/__init__.py"
  - "config.yaml"
---

# AppConfig

## Overview

`AppConfig` is the Pydantic model representing the full application configuration. It is loaded once from `config.yaml` via `load_config()` and cached with `@lru_cache`. All subsystems read from it rather than accessing environment variables directly.

## Location

Defined in `config/__init__.py`. Config file: `config.yaml` (repo root).

## Details

`AppConfig` is composed of nested sub-models:

| Sub-model | Field | Key settings |
|-----------|-------|--------------|
| `Settings` | `settings` | `home_dir` — state directory path |
| `VirtualComputerConfig` | `virtual_computer` | `home_dir` — agent workspace path |
| `FeaturesConfig` | `features` | `image_generation`, `music_generation`, `desktop`, `visual_grounding`, `custom_tools` (booleans) |
| `ToolsConfig` | `tools` | Browser headless mode, human simulation timing, tab limits |
| `DesktopConfig` | `desktop` | VNC display, resolution, WebSocket port |
| `ParallelConfig` | `parallel` | `enabled`, `max_concurrent` for sub-agents |
| `GoalsConfig` | `goals` | `enabled`, poll interval, max concurrent tasks, timezone, notifications |
| `IntegrationsConfig` | `integrations` | Unix socket paths for supervisor/broker IPC |

### `config.yaml` format

Values use `${ENV_VAR:-default}` syntax for env-var interpolation. Scalar types (bool, int, float) are inferred from the resolved string. Example:

```yaml
features:
  desktop: ${ENABLE_DESKTOP:-false}
  image_generation: ${ENABLE_IMAGE_GEN:-false}
```

`load_config()` resolves all `${...}` placeholders before Pydantic validation.

## Key Function

```python
from config import load_config

cfg = load_config()  # cached; call freely
```

## Related Entities

- [[AgentProfile]] — profile settings complement AppConfig per-agent settings
- [[Task Engine]] — reads `GoalsConfig`

## Sources

- `config/__init__.py`
