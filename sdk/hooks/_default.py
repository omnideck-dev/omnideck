"""Factory for the standard set of hooks used by all agents."""

from __future__ import annotations

from sdk.agent import Agent
from sdk.context import ContextManager

from ._types import Hook

from ._budget_guard import BudgetGuard
from ._context_hook import ContextHook
from ._loaded_skill_hook import LoadedSkillHook
from ._logging_hook import LoggingHook
from ._loop_detector import LoopDetector
from ._nudge_hook import NudgeHook
from ._result_cap import ToolResultCapHook
from ._stop_hook import StopHook


def default_hooks(
    agent: Agent,
    *,
    max_iterations: int = 0,
    ctx_manager: ContextManager | None = None,
) -> list[Hook]:
    """Return the standard set of hooks used by all agents."""
    hooks: list[Hook] = [NudgeHook(), StopHook()]
    if max_iterations > 0:
        hooks.append(BudgetGuard(max_iterations))
    hooks.append(LoopDetector())
    hooks.append(LoggingHook(agent))
    hooks.append(LoadedSkillHook())
    context_window = getattr(agent, "context_window", 0) or 0
    if context_window > 0:
        hooks.append(ToolResultCapHook(context_window))
    if ctx_manager is not None:
        hooks.append(ContextHook(ctx_manager, max_iterations=max_iterations))
    return hooks
