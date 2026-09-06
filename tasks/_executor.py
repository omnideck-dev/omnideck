"""TaskExecutor — bridges TaskResult + Task to the agent turn machinery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents import get_agent_profile
from agent_runtime import AgentRuntime, AgentRunRequest, RunPolicy

if TYPE_CHECKING:
    from agents._agent_profiles import AgentProfile
    from tasks._models import Routine, Task, TaskResult
    from tasks._store import TaskStore

class TaskExecutor:
    """Execute a single TaskResult as an agent turn."""

    def __init__(self, store: TaskStore, runtime: AgentRuntime) -> None:
        self._store = store
        self._runtime = runtime

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
        profile = self._profile_for(task)
        handle = await self._runtime.start(AgentRunRequest(
            conversation_id=conversation_id, message=instruction, attachments=None, profile_id=profile.id,
            policy=RunPolicy(
                restore_skills=False, persist_skills=False, include_memory=False,
                conversation_lifetime="run", agent_name="TASK_AGENT",
            ),
        ))
        try:
            self._store.set_agent_run(task_result.id, conversation_id=conversation_id, agent_run_id=handle.run_id)
            result = await handle.wait()
        except BaseException:
            # Routine cancellation is an explicit ownership action. A passive
            # RunHandle.wait cancellation elsewhere never stops the shared run.
            handle.cancel()
            await handle.wait()
            raise
        result.raise_for_status()
        return result.output or "", [artifact.path for artifact in result.artifacts if artifact.path]

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
