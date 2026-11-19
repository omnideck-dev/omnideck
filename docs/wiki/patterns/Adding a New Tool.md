---
title: Adding a New Tool
type: pattern
tags: [tools, agent, extension, skills]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "tools/"
  - "skills/"
  - "agent_core/tools/"
---

# Adding a New Tool

## Overview

Tools are Python callables with Google-style docstrings. The agent discovers tools
through the [[Skill System]]: a tool belongs to a **tool category**, a category is
granted by one or more skills, and a profile (or a mid-turn `load_skill` call) is what
actually puts the category's tools in front of the model.

Formerly this pattern pointed at `sdk/skills/build_agent_state()`; that package is
dead. Tool categories are now assembled by `skills/_tool_categories.py:tool_categories()`.

## Where It's Used

Tool-call dispatch happens in `agent_core/tools/_helpers.py` (`_execute_tool_call()`),
schema generation in `agent_core/tools/_callable_schema.py`. Tools are grouped into
categories in `skills/_tool_categories.py`, and categories are granted to a running
turn either by an `AgentProfile`'s `skills` list at turn start, or by the model calling
`load_skill(name)` mid-turn (`skills/_tools.py`).

## How to Extend This

### 1. Create the tool function

Create a file in the appropriate category under `tools/`. For a new virtual-computer
operation:

```
tools/virtual_computer/my_new_op.py
```

Write the function with a Google-style docstring. The first line is the tool
description shown to the LLM:

```python
import logging

from agent_core.events import AgentEvent, publish_event

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
- **Must have a Google-style docstring.** `callable_to_json_schema()` parses it
  directly into the tool schema sent to the model.
- **Never put implementation details in docstrings** — describe what the tool does
  and its args, not how it's implemented.
- **Return a string** (or something JSON-serializable) — the model reads the return
  value as text.
- **Emit events** with `publish_event(AgentEvent(payload=...))` from `agent_core.events`
  if the tool produces side effects the UI should display — see [[Event System]].

### 2. Export from the category `__init__.py`

```python
# tools/virtual_computer/__init__.py
from .my_new_op import my_new_tool
__all__ = [..., "my_new_tool"]
```

### 3. Add it to a tool category

If the tool belongs to an existing category (e.g. `coding` for a virtual-computer
operation), add the callable to that category's list in
`skills/_tool_categories.py:_static_tool_categories()`. If it needs a new category,
add a new `ToolCategory(...)` entry there (or, for an integration-backed tool, a new
entry in `_INTEGRATION_TOOL_CATEGORIES`).

A skill then has to actually grant the category — either an existing `SkillRecord`'s
`tool_categories` list (editable via the Skills UI, backed by `skills/_store.py`), or
a new one. Default skill assignments for new profiles are installed by a migration
(`migrations/_006_install_default_skills.py`).

### 4. Write a test

Create a unit test under `tests/unit/tools/` (mirroring the source structure — e.g.
`tests/unit/tools/virtual_computer/`).

## Deviations From Textbook Form

- Tools are plain async functions, not classes. No decorator is required for basic
  registration — the schema generator inspects the docstring and type annotations
  directly. (Some browser tools *do* use decorators like `@emit_screenshot_after` for
  event emission, but that's orthogonal to being callable as a tool.)
- Tool arguments must be JSON-serializable (str, int, float, bool, list, dict) — the
  model constructs the call as JSON.
- A tool only becomes callable through a **tool category** granted by a **skill** —
  adding the function and exporting it is not sufficient on its own; see step 3.

## Related Concepts

- [[Tool Architecture]] — full overview of all tool categories
- [[Skill System]] — how categories become available to a running agent
- [[Hooks System]] — `before_tool` / `after_tool` hook phases wrap every call
- [[Event System]] — how tools emit events visible in the UI
