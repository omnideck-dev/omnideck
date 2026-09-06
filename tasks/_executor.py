"""TaskExecutor — bridges TaskResult + Task to the agent turn machinery."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agents import build_agent, get_agent_profile, resolve_agent_runtime_metadata
from browser.runtime import get_browser_runtime
from conversations import EventsLogWriter, run_conversation_exit_hooks
from sdk import default_hooks, run_turn
from sdk.context import ContextManager, ConversationHistory, LLMCompactionStrategy
from sdk.events._context import (
    agent_span,
    publish_event,
)
from sdk.events._models import (
    AgentEvent,
    FileOutputPayload,
    UserMessagePayload,
)
from sdk.agent_state import build_agent_state
from sdk.turn import turn_scope

if TYPE_CHECKING:
    from agents._agent_profiles import AgentProfile
    from tasks._models import Routine, Task, TaskResult
    from tasks._store import TaskStore

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Execute a single TaskResult as an agent turn."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    async def run(self, task_result: TaskResult, task: Task) -> tuple[str, list[str]]:
        """Execute a task and return (result_text, file_output_paths)."""
        run = self._store.get_run(task_result.run_id)
        if not run:
            msg = f"Run {task_result.run_id} not found"
            raise ValueError(msg)
        routine = self._store.get_routine(run.routine_id)
        if not routine:
            msg = f"Routine {run.routine_id} not found"
            raise ValueError(msg)

        instruction = self._build_instruction(task_result, task, routine)
        conversation_id = f"routines/{run.routine_id}/{run.id}/{task_result.id}"
        self._store.set_conversation_id(task_result.id, conversation_id)

        try:
            profile = self._profile_for(task)
            agent_state = await build_agent_state(profile)
            agent = await resolve_agent_runtime_metadata(
                build_agent(profile, tools=agent_state.tools, name="TASK_AGENT"),
            )

            history = ConversationHistory(
                system_message=agent.instruction,
                conversation_id=conversation_id,
            )

            file_paths: list[str] = []

            def _capture_file_output(event: AgentEvent) -> None:
                if isinstance(event.payload, FileOutputPayload) and event.payload.path:
                    file_paths.append(event.payload.path)

            events_log = EventsLogWriter(conversation_id)
            # Observers subscribe around the scope so the turn_scope-owned
            # turn_end at the end of the turn still reaches them.
            history.subscribe(events_log.handle_event)
            history.subscribe(_capture_file_output)
            try:
                async with turn_scope(history, conversation_id=conversation_id):
                    ctx_manager = ContextManager(
                        history=history,
                        agent_state=agent_state,
                        context_limit=agent.context_window,
                        agent_name=agent.name,
                        strategies=[
                            LLMCompactionStrategy(threshold=agent.compaction_threshold),
                        ],
                    )
                    hooks = default_hooks(
                        agent,
                        max_iterations=agent.max_iterations,
                        ctx_manager=ctx_manager,
                    )
                    async with agent_span(agent.name, instruction=instruction, agent_state=agent_state):
                        await get_browser_runtime().prepare_current_agent_browser(
                            agent_profile_id=profile.id,
                            browser_profile_id=profile.browser_profile_id,
                        )
                        publish_event(
                            AgentEvent(
                                payload=UserMessagePayload(
                                    type="user_message",
                                    content=instruction,
                                )
                            )
                        )
                        result = await run_turn(history, agent, hooks=hooks)
            finally:
                # Unsubscribe synchronously before the await so a cancellation
                # mid-drain can't skip the unsubscribes and leak observers onto
                # the history. Drain still flushes in-flight events: it waits on
                # already-created observer tasks regardless of the list.
                history.unsubscribe(events_log.handle_event)
                history.unsubscribe(_capture_file_output)
                await history.drain_observers()

            return result or "", file_paths
        finally:
            # Routine task conversations are single-execution resources rather
            # than server-cached interactive conversations. Always run their
            # exit hooks so browser contexts and other conversation-scoped
            # resources are released after success, failure, or cancellation.
            await run_conversation_exit_hooks(conversation_id)

    def _profile_for(self, task: Task) -> AgentProfile:
        """The agent profile for a task, or raise if it's missing."""
        if not task.agent_profile:
            msg = f"Task {task.id} has no agent_profile set"
            raise RuntimeError(msg)
        profile = get_agent_profile(task.agent_profile)
        if profile is None:
            msg = f"Agent profile '{task.agent_profile}' not found for task {task.id}"
            raise RuntimeError(msg)
        return profile

    def _build_instruction(self, task_result: TaskResult, task: Task, routine: Routine) -> str:
        """Build the agent instruction, injecting predecessor task results."""
        parts = [
            f"## Routine\n{routine.description}\n",
            f"## Task\n{task.instruction}\n",
        ]

        deps = task.depends_on or []
        if deps:
            predecessor_results = self._store.get_completed_results_for_tasks(
                run_id=task_result.run_id,
                task_ids=deps,
            )
            if predecessor_results:
                parts.append("## Results from previous tasks\n")
                for desc, result_text in predecessor_results:
                    parts.append(f"### {desc}\n{result_text}\n")

        return "\n".join(parts)


__all__ = ["TaskExecutor"]
