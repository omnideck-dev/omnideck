"""Tests for tasks._executor.

The executor resolves a task's agent profile before composing its agent.
``_profile_for`` must surface a missing or unknown profile as a clear
RuntimeError rather than failing confusingly downstream at routine-run time.
"""

from __future__ import annotations

import pytest

from tasks._executor import TaskExecutor
from tasks._models import Task


@pytest.mark.unit
def test_profile_for_raises_when_task_has_no_profile() -> None:
    task = Task(routine_id="g1", description="orphan task", instruction="do the thing", agent_profile=None)
    executor = TaskExecutor(store=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no agent_profile"):
        executor._profile_for(task)


@pytest.mark.unit
def test_profile_for_raises_when_profile_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tasks._executor.get_agent_profile", lambda _id: None)
    task = Task(routine_id="g1", description="task", instruction="prompt", agent_profile="does_not_exist")
    executor = TaskExecutor(store=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="does_not_exist"):
        executor._profile_for(task)
