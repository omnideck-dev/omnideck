"""Generic context strategy contract implemented by applications."""

from enum import StrEnum
from typing import Protocol
from ._history import ConversationHistory
from ._models import ContextStats

class TriggerPoint(StrEnum):
    """When a strategy should be evaluated."""

    BEFORE_MODEL_CALL = "before_model_call"
    AFTER_MODEL_CALL = "after_model_call"


class ContextStrategy(Protocol):
    """Interface for context management strategies."""

    @property
    def trigger(self) -> TriggerPoint:
        """When this strategy should be evaluated."""
        ...

    def should_apply(self, history: ConversationHistory, stats: ContextStats) -> bool:
        """Whether this strategy needs to act given the current state."""
        ...

    async def apply(self, history: ConversationHistory, stats: ContextStats) -> None:
        """Mutate *history* to reduce context usage."""
        ...
