"""Factory for the standard set of hooks used by all agents."""

from __future__ import annotations

from agent_core.agent import Agent
from agent_core.context import ContextManager

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
    ctx_manager: ContextManager | None = None,
) -> list[Hook]:
    """Return the standard set of hooks used by all agents."""
    hooks: list[Hook] = [NudgeHook(), StopHook()]
    if agent.max_iterations > 0:
        hooks.append(BudgetGuard(agent.max_iterations))
    hooks.append(LoopDetector())
    hooks.append(LoggingHook(agent))
    hooks.append(LoadedSkillHook())
    hooks.append(ToolResultCapHook(agent.context_window))
    if ctx_manager is not None:
        hooks.append(ContextHook(ctx_manager, max_iterations=agent.max_iterations))
    return hooks
