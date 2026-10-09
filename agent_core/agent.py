"""Execution configuration for an agent, independent of saved profiles."""

from typing import Any

from pydantic import BaseModel


class Agent(BaseModel):
    """Represents the configuration for a generic agent.

    Attributes:
        name: The agent's name.
        description: Description of the agent.
        instruction: The root prompt or instruction for the agent.
        model: The model name to use.
        options: Model options passed to the provider (temperature, top_p, etc.).
        think: Whether the model should think. Not all models support thinking.
        context_window: Model's context window in tokens, used as the compaction denominator.
        compaction_threshold: Fill ratio (0.0–1.0) at which compaction fires.
        max_iterations: Maximum tool-call loop iterations before forced stop.
    """

    name: str
    description: str
    instruction: str
    provider: str
    model: str
    options: dict[str, Any]
    think: bool = False
    context_window: int = 0
    compaction_threshold: float = 0.75
    max_iterations: int = 0
