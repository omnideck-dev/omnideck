"""Agent capability definition for the Browser tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import cache
from importlib.resources import files
from typing import Any

from sdk.capabilities import AgentCapability
from skills._tool_categories import tool_categories


@cache
def _definition() -> dict[str, Any]:
    resource = files("tools.browser").joinpath("capability.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid Browser capability definition")
    return value


async def browser_capability() -> AgentCapability:
    """Build the application-controlled capability for Browser tools."""
    definition = _definition()
    categories = await tool_categories()
    tools: list[Callable[..., Any]] = []
    for category_id in definition.get("tool_categories", []):
        category = categories.get(str(category_id))
        if category is not None:
            tools.extend(category.tools)
    return AgentCapability(
        id=str(definition.get("id", "browser")),
        name=str(definition.get("name", "Browser")),
        prompt=str(definition.get("prompt", "")),
        tools=tools,
    )


__all__ = ["browser_capability"]
