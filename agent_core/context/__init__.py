"""Context management for conversation history and compaction."""

from ._estimator import estimate_tokens
from ._history import ConversationHistory
from ._manager import ContextManager
from ._models import ContextStats
from ._view import GOAL_STATE_PREFIX, GOAL_WAKEUP_PREFIX, SYSTEM_ACTIVITY_PREFIX
from ._strategy import (
    ContextStrategy,
    TriggerPoint,
)

__all__ = [
    "ContextManager",
    "ContextStats",
    "ContextStrategy",
    "ConversationHistory",
    "GOAL_STATE_PREFIX",
    "GOAL_WAKEUP_PREFIX",
    "SYSTEM_ACTIVITY_PREFIX",
    "TriggerPoint",
    "estimate_tokens",
]
