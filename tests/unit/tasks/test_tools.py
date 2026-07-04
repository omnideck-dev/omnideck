"""Tests for tasks._tools planning tools."""

import re
from typing import Any

import pytest

import tasks
from tasks import _singleton
from tasks._tools import commit_routine, list_routines, list_tasks

_TASK = {"key": "t1", "description": "task 1", "instruction": "do the thing", "agent_profile": "computron"}


async def create_routine(
    description: str,
    tasks: list[dict[str, Any]],
    cron: str | None = None,
    timezone: str | None = None,
) -> str:
    """Build a draft dict and commit it, matching the old create_routine signature."""
    draft: dict[str, Any] = {"description": description, "tasks": tasks}
    if cron is not None:
        draft["cron"] = cron
    if timezone is not None:
        draft["timezone"] = timezone
    return await commit_routine(draft)


@pytest.fixture(autouse=True)
def _init_store(tmp_path):
    """Initialize the global store for each test."""
    from tasks._file_store import FileTaskStore

    _singleton._store = FileTaskStore(tmp_path / "routines")
    yield
    _singleton._store = None


@pytest.fixture(autouse=True)
def _seed_profiles(tmp_path, monkeypatch):
    """Isolate profiles to tmp and seed the ones tests reference."""
    from agents._agent_profiles import AgentProfile, save_agent_profile

    monkeypatch.setattr(
        "agents._agent_profiles._profiles_dir",
        lambda: tmp_path / "agent_profiles",
    )
    save_agent_profile(AgentProfile(id="computron", name="Computron", model="m"))
    save_agent_profile(AgentProfile(id="code_expert", name="Code Expert", model="m"))


def _extract_id(result_str):
    """Extract id=... from a tool result string."""
    match = re.search(r"id=(\w+)", result_str)
    assert match, f"No id found in: {result_str}"
    return match.group(1)


@pytest.mark.unit
class TestCreateRoutine:
    """Test create_routine tool."""

    async def test_one_shot_routine_spawns_run(self):
        """One-shot routine (no cron) auto-spawns a run."""
        result = await create_routine("one shot routine", tasks=[_TASK])
        assert "one shot routine" in result
        routine_id = _extract_id(result)

        store = tasks.get_store()
        runs = store.get_routine_runs(routine_id)
        assert len(runs) == 1

    async def test_recurring_routine_no_auto_run(self):
        """Recurring routine does not auto-spawn a run."""
        result = await create_routine("recurring", tasks=[_TASK], cron="0 */2 * * *")
        routine_id = _extract_id(result)

        store = tasks.get_store()
        runs = store.get_routine_runs(routine_id)
        assert len(runs) == 0

    async def test_empty_description_returns_error(self):
        """Empty description returns an error string."""
        result = await create_routine("", tasks=[_TASK])
        assert "Error" in result

    async def test_empty_tasks_returns_error(self):
        """Empty tasks list returns an error string."""
        result = await create_routine("routine", tasks=[])
        assert "Error" in result

    async def test_bad_cron_returns_error(self):
        """Invalid cron returns an error string."""
        result = await create_routine("routine", tasks=[_TASK], cron="not a cron")
        assert "Error" in result

    async def test_creates_all_tasks(self):
        """All submitted tasks are persisted."""
        tasks_input = [
            {"key": "a", "description": "A", "instruction": "do A", "agent_profile": "computron"},
            {"key": "b", "description": "B", "instruction": "do B", "agent_profile": "computron"},
        ]
        result = await create_routine("multi", tasks=tasks_input)
        routine_id = _extract_id(result)

        store = tasks.get_store()
        stored = store.list_tasks(routine_id)
        assert len(stored) == 2
        assert {t.description for t in stored} == {"A", "B"}

    async def test_task_dependencies_resolved(self):
        """depends_on keys are resolved to real task IDs."""
        tasks_input = [
            {"key": "first", "description": "first task", "instruction": "do first", "agent_profile": "computron"},
            {
                "key": "second", "description": "second task", "instruction": "do second",
                "depends_on": ["first"], "agent_profile": "computron",
            },
        ]
        result = await create_routine("dep routine", tasks=tasks_input)
        routine_id = _extract_id(result)

        store = tasks.get_store()
        stored = store.list_tasks(routine_id)
        by_desc = {t.description: t for t in stored}
        first_id = by_desc["first task"].id
        assert by_desc["second task"].depends_on == [first_id]

    async def test_missing_agent_profile_returns_error(self):
        """A task without agent_profile returns an error."""
        task = {"key": "t1", "description": "task", "instruction": "do it"}
        result = await create_routine("routine", tasks=[task])
        assert "Error" in result
        assert "agent_profile" in result

    async def test_task_agent_profile_persists(self):
        """Task agent_profile is saved on the stored task."""
        task = {**_TASK, "agent_profile": "code_expert"}
        result = await create_routine("routine", tasks=[task])
        routine_id = _extract_id(result)

        store = tasks.get_store()
        stored = store.list_tasks(routine_id)
        assert stored[0].agent_profile == "code_expert"

    async def test_disabled_agent_profile_rejected(self, tmp_path, monkeypatch):
        """Referencing a disabled profile returns an error with available list."""
        # Wire up an isolated profiles directory with one enabled + one disabled
        from agents._agent_profiles import AgentProfile, save_agent_profile
        monkeypatch.setattr(
            "agents._agent_profiles._profiles_dir",
            lambda: tmp_path / "agent_profiles",
        )
        save_agent_profile(AgentProfile(id="on", name="On", model="m", enabled=True))
        save_agent_profile(AgentProfile(id="off", name="Off", model="m", enabled=False))

        task = {**_TASK, "agent_profile": "off"}
        result = await create_routine("routine", tasks=[task])
        assert "Error" in result
        assert "disabled" in result
        assert "'off'" in result
        # Error should list enabled-only available profiles
        assert "'on'" in result
        assert "'off'" not in result.split("Available:")[-1]

    async def test_unknown_agent_profile_rejected(self, tmp_path, monkeypatch):
        """Referencing an unknown profile returns an error."""
        from agents._agent_profiles import AgentProfile, save_agent_profile
        monkeypatch.setattr(
            "agents._agent_profiles._profiles_dir",
            lambda: tmp_path / "agent_profiles",
        )
        save_agent_profile(AgentProfile(id="on", name="On", model="m", enabled=True))

        task = {**_TASK, "agent_profile": "nope"}
        result = await create_routine("routine", tasks=[task])
        assert "Error" in result
        assert "unknown" in result
        assert "'nope'" in result

    async def test_duplicate_key_returns_error(self):
        """Duplicate task keys return an error without writing anything."""
        tasks_input = [
            {"key": "dup", "description": "A", "instruction": "inst"},
            {"key": "dup", "description": "B", "instruction": "inst"},
        ]
        result = await create_routine("routine", tasks=tasks_input)
        assert "Error" in result

    async def test_unknown_dep_returns_error(self):
        """A depends_on key not in the task list returns an error."""
        tasks_input = [
            {"key": "a", "description": "A", "instruction": "inst", "depends_on": ["nonexistent"]},
        ]
        result = await create_routine("routine", tasks=tasks_input)
        assert "Error" in result

    async def test_forward_dep_returns_error(self):
        """A task may not depend on a key that appears later in the list."""
        tasks_input = [
            {"key": "a", "description": "A", "instruction": "inst", "depends_on": ["b"]},
            {"key": "b", "description": "B", "instruction": "inst"},
        ]
        result = await create_routine("routine", tasks=tasks_input)
        assert "Error" in result

    async def test_missing_task_key_returns_error(self):
        """A task without a key returns an error."""
        result = await create_routine("routine", tasks=[{"description": "A", "instruction": "inst"}])
        assert "Error" in result

    async def test_missing_task_instruction_returns_error(self):
        """A task without instruction returns an error."""
        result = await create_routine("routine", tasks=[{"key": "a", "description": "A"}])
        assert "Error" in result

    async def test_one_shot_run_includes_task_results(self):
        """The auto-spawned run has task results for all tasks, not zero."""
        tasks_input = [
            {"key": "a", "description": "A", "instruction": "do A", "agent_profile": "computron"},
            {"key": "b", "description": "B", "instruction": "do B", "agent_profile": "computron"},
        ]
        result = await create_routine("routine", tasks=tasks_input)
        routine_id = _extract_id(result)

        store = tasks.get_store()
        runs = store.get_routine_runs(routine_id)
        assert len(runs) == 1
        task_results = store.get_task_results(runs[0].id)
        assert len(task_results) == 2


@pytest.mark.unit
class TestListTools:
    """Test list_routines and list_tasks tools."""

    async def test_list_routines(self):
        """List routines returns all routines."""
        await create_routine("g1", tasks=[_TASK])
        await create_routine("g2", tasks=[_TASK])
        result = await list_routines()
        assert "g1" in result
        assert "g2" in result

    async def test_list_routines_filtered(self):
        """List routines with status filter."""
        routine_id = _extract_id(await create_routine("g1", tasks=[_TASK]))
        store = tasks.get_store()
        store.set_routine_status(routine_id, "paused")
        result = await list_routines(status="active")
        assert "No routines found" in result

    async def test_list_tasks(self):
        """List tasks for a routine."""
        routine_id = _extract_id(await create_routine("routine", tasks=[_TASK]))
        result = await list_tasks(routine_id)
        assert "task 1" in result

    async def test_timezone_default_to_utc(self):
        """Routine timezone defaults to UTC."""
        result = await create_routine("routine with tz", tasks=[_TASK])
        assert "timezone=UTC" in result

    async def test_timezone_parameter(self):
        """Routine timezone is set when provided."""
        result = await create_routine("routine with tz", tasks=[_TASK], cron="0 * * * *", timezone="America/Chicago")
        assert "timezone=America/Chicago" in result

