"""Application operations spanning routine execution and persistent state."""

from tasks._runner import TaskRunner
from tasks._store import TaskStore


class RoutineService:
    """Coordinate routine deletion without exposing execution storage details."""

    def __init__(self, store: TaskStore, runner: TaskRunner | None) -> None:
        self._store = store
        self._runner = runner

    async def delete_routine(self, routine_id: str) -> None:
        """Stop owned work, then delete all persistent state before admitting more work."""
        if self._runner is None:
            self._store.delete_routine(routine_id)
            return
        async with self._runner.stop_routine(routine_id):
            self._store.delete_routine(routine_id)

    async def delete_run(self, run_id: str) -> None:
        """Stop this run and delete its persistent state without affecting other runs."""
        if self._runner is None:
            self._store.delete_run(run_id)
            return
        async with self._runner.stop_run(run_id):
            self._store.delete_run(run_id)
