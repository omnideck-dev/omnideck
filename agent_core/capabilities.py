"""Application-controlled capabilities granted to an agent run."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentCapability:
    """A non-loadable bundle of tools and prompt guidance."""

    id: str
    name: str
    prompt: str
    tools: list[Callable[..., Any]]


__all__ = ["AgentCapability"]
