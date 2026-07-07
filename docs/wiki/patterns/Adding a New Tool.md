---
title: Adding a New Tool
type: pattern
tags: [tools, agent, extension]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "tools/"
  - "sdk/skills/"
---

# Adding a New Tool

## Overview

Tools are Python callables with Google-style docstrings. The LLM uses the docstring to understand when and how to call the tool. The SDK discovers tools by inspecting the callable list passed to `run_turn()`.

## Where It's Used

All agent tool calls go through `sdk/turn/_execution.py`. Tools are assembled per-turn in `sdk/skills/build_agent_state()` based on the profile's `skills` list.

## How to Extend This

### 1. Create the tool function

Create a file in the appropriate category under `tools/`. For a new file operation:

```
tools/virtual_computer/my_new_op.py
```

Write the function with a Google-style docstring. The first line of the docstring is the tool description shown to the LLM:

```python
import logging
from sdk.events import publish_event

logger = logging.getLogger(__name__)


async def my_new_tool(arg1: str, arg2: int = 10) -> str:
    """Do something useful with a file.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2. Default is 10.

    Returns:
        A string result for the LLM to read.
    """
    # implementation
    result = ...
    return str(result)
```

Rules:
- **Must have Google-style docstring.** The SDK uses this as the tool schema for the LLM.
- **Never put implementation details in docstrings** — describe what the tool does and its args, not how it's implemented.
- **Return a string** (or something JSON-serializable) — the LLM reads the return value as text.
- **Emit events** if the tool produces side-effects the UI should display (use `publish_event`).

### 2. Export from the category `__init__.py`

```python
# tools/virtual_computer/__init__.py
from tools.virtual_computer.my_new_op import my_new_tool
__all__ = [..., "my_new_tool"]
```

### 3. Register in a skill

Skills determine which tools are available to an agent. If the tool belongs to an existing skill, add it to that skill's tool list in `sdk/skills/`. If it's a new category, create a new skill entry.

The default skills configuration lives in `agents/_agent_profiles.py` (default profile's `skills` list) and the migration `migrations/_006_install_default_skills.py`.

### 4. Write a test

Create a unit test in `tests/unit/tools/` (or the appropriate sub-directory mirroring source structure).

## Deviations From Textbook Form

- Tools are plain async functions, not classes. No decorator needed — the SDK inspects the docstring and type annotations directly.
- Tool arguments must be JSON-serializable (str, int, float, bool, list, dict). The LLM constructs the call JSON.
- Use `publish_event(payload)` from `sdk/events` to surface activity in the UI — don't return binary data directly.

## Related Concepts

- [[Tool Architecture]] — full overview of all tool categories
- [[Hooks System]] — `before_tool` and `after_tool` hook phases wrap every call
- [[Event System]] — how tools emit events visible in the UI
