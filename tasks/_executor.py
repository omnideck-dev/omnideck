"""TaskExecutor — bridges TaskResult + Task to the agent turn machinery."""

from __future__ import annotations

import logging
from uuid import uuid4
from typing import TYPE_CHECKING

from agents import get_agent_profile
from agent_runtime import AgentRunner
from conversations import EventsLogWriter, run_conversation_exit_hooks
from sdk.context import ConversationHistory
from sdk.events import AgentEvent, FileOutputPayload
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
        self._runner = AgentRunner()

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
            history = ConversationHistory(conversation_id=conversation_id)

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
                    result = await self._runner.execute(
                        profile=profile,
                        history=history,
                        message=instruction,
                        run_id=f"run_{uuid4().hex}",
                        name="TASK_AGENT",
                    )
            finally:
                # Unsubscribe synchronously before the await so a cancellation
                # mid-drain can't skip the unsubscribes and leak observers onto
                # the history. Drain still flushes in-flight events: it waits on
                # already-created observer tasks regardless of the list.
                history.unsubscribe(events_log.handle_event)
                history.unsubscribe(_capture_file_output)
                await history.drain_observers()

            return result.output or "", file_paths
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
