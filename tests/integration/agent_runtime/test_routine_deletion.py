"""Delete through HTTP while real routine executions still own their records."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agent_core.turn import get_execution_context
from conversations import load_events_jsonl
from providers._fake import FakeProvider
from server._task_routes import register_task_routes
from tasks import TaskExecutor, TaskRunner
from tests.e2e._protocol import call_tool, say, spawn


@pytest.mark.parametrize("target", ["routine", "run"])
async def test_deletion_awaits_owned_trees_and_preserves_unrelated_work(harness, monkeypatch, target):
    h = harness
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: FakeProvider())
    monkeypatch.setattr("server._task_routes.get_store", lambda: h.store)
    entered, cleaning = asyncio.Queue(), asyncio.Queue()
    release_work, release_cleanup = asyncio.Event(), asyncio.Event()
    effects = set()

    async def delayed_effect() -> str:
        """Hold an operation until released, with separately delayed cancellation cleanup."""
        context = get_execution_context()
        entered.put_nowait(context)
        try:
            await release_work.wait()
            effects.add(context.conversation_id)
            return "effect completed"
        finally:
            if context.control.stop_event.is_set():
                cleaning.put_nowait(context)
                await release_cleanup.wait()

    h.skill("effect", delayed_effect)
    h.profile("root", allow_spawn=True)
    h.profile("branch", allow_spawn=True)
    h.profile("leaf", skills=["effect"])
    message = spawn(
        spawn(call_tool("delayed_effect"), profile="leaf", name="LEAF"), profile="branch", name="BRANCH",
    ) + say("completed")
    routine = h.store.create_routine("delete target", auto_run=False)
    first = h.store.create_task(routine.id, "one", message, agent_profile="root")
    h.store.create_task(routine.id, "two", message, agent_profile="root")
    pending = h.store.create_task(
        routine.id, "dependent", say("dependent finished"), agent_profile="root", depends_on=[first.id],
    )
    runs = [h.store.queue_run(routine.id) for _ in range(2)]
    other = h.store.create_routine("unrelated", auto_run=False)
    h.store.create_task(other.id, "other", message, agent_profile="root")
    other_run = h.store.queue_run(other.id)
    config = h.config.routines.model_copy(update={"max_concurrent": 6, "shutdown_timeout": 0})
    runner = TaskRunner(h.store, TaskExecutor(h.store, h.manager), config)
    app = web.Application()
    app["task_runner"] = runner
    register_task_routes(app)
    deletion = None
    duplicate = None
    async with TestClient(TestServer(app)) as client:
        try:
            await runner._tick()
            contexts = [await asyncio.wait_for(entered.get(), 5) for _ in range(5)]
            affected_runs = runs if target == "routine" else runs[:1]
            affected = {
                result.conversation_id for run in affected_runs for result in h.store.get_task_results(run.id)
                if result.conversation_id
            }
            handles = {context.conversation_id: h.manager.get(context.run_id) for context in contexts}
            survivors = set(handles) - affected

            original_delete = getattr(h.store, f"delete_{target}")

            def checked_delete(identifier):
                if getattr(h.store, f"get_{target}")(identifier) is None:
                    return original_delete(identifier)
                # These checks run at the exact destructive boundary, while the
                # real event files still exist and can prove cleanup ordering.
                for conversation in affected:
                    handle = handles[conversation]
                    assert h.manager.get(handle.run_id) is None
                    assert conversation in h.exited_conversations
                    assert handle._session.history._observers == []
                    assert not handle._session.history._async_obs_tasks
                    events = load_events_jsonl(conversation)
                    ends = [event for event in events if event["type"] == "agent_completed"]
                    assert len(ends) == 3
                    assert all(event["status"] == "stopped" for event in ends)
                return original_delete(identifier)

            monkeypatch.setattr(h.store, f"delete_{target}", checked_delete)
            path = f"/api/routines/{routine.id}"
            if target == "run":
                path += f"/runs/{runs[0].id}"
            deletion = asyncio.create_task(client.delete(path))
            cancelled = [await asyncio.wait_for(cleaning.get(), 5) for _ in affected]
            assert {context.conversation_id for context in cancelled} == affected
            assert not deletion.done()
            assert h.store.get_routine(routine.id) is not None
            assert all(h.store.get_run(run.id) is not None for run in runs)

            duplicate = asyncio.create_task(getattr(runner, f"delete_{target}")(
                routine.id if target == "routine" else runs[0].id,
            ))
            await asyncio.sleep(0)
            assert not duplicate.done()

            # Exercise admission while deletion is suspended: newly queued runs
            # of a deleting routine, and newly ready tasks of a deleting run.
            if target == "routine":
                late_run = h.store.queue_run(routine.id)
            else:
                result = next(r for r in h.store.get_task_results(runs[0].id) if r.task_id == first.id)
                h.store.mark_task_result_completed(result.id, "dependency satisfied during cleanup")
            await runner._tick()
            assert entered.empty()
            if target == "routine":
                assert all(result.status == "pending" for result in h.store.get_task_results(late_run.id))
            else:
                assert next(r for r in h.store.get_task_results(runs[0].id) if r.task_id == pending.id).status == "pending"

            release_cleanup.set()
            response = await asyncio.wait_for(deletion, 5)
            assert await asyncio.wait_for(duplicate, 5) == []
            assert response.status == 200
            assert runner.status["active_tasks"] == len(survivors)
            assert not effects
            assert all(h.manager.get(handles[c].run_id) is not None for c in survivors)
            assert all(h.manager.get(handles[c].run_id) is None for c in affected)
            assert all(not load_events_jsonl(c) for c in affected)
            if target == "routine":
                assert h.store.get_routine(routine.id) is None
                assert h.store.get_routine_runs(routine.id) == []
            else:
                assert h.store.get_routine(routine.id) is not None
                assert h.store.get_run(runs[0].id) is None
                assert h.store.get_run(runs[1].id) is not None
            assert h.store.get_run(other_run.id) is not None

            release_work.set()
            await asyncio.wait_for(asyncio.gather(*(handle.wait() for handle in handles.values())), 5)
            await asyncio.wait_for(asyncio.gather(*runner._running.values()), 5)
            await runner._tick()
            await asyncio.wait_for(asyncio.gather(*runner._running.values()), 5)
            await runner._tick()
            assert effects == survivors
            assert runner.status["active_tasks"] == 0
        finally:
            release_cleanup.set()
            release_work.set()
            if deletion is not None:
                await deletion
            if duplicate is not None:
                await duplicate
            await runner.stop()


async def test_shutdown_waits_for_cleanup_already_started_by_deletion(harness, monkeypatch):
    h = harness
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: FakeProvider())
    entered, cleaning, release = (asyncio.Event() for _ in range(3))

    async def delayed_cleanup() -> str:
        """Keep cancellation cleanup open while runner shutdown begins."""
        entered.set()
        try:
            await asyncio.Event().wait()
            return "unreachable"
        finally:
            cleaning.set()
            await release.wait()

    h.skill("cleanup", delayed_cleanup)
    h.profile(skills=["cleanup"])
    routine = h.store.create_routine("delete during shutdown", auto_run=False)
    h.store.create_task(routine.id, "hold", call_tool("delayed_cleanup"), agent_profile="leaf")
    run = h.store.queue_run(routine.id)
    config = h.config.routines.model_copy(update={"shutdown_timeout": 0})
    runner = TaskRunner(h.store, TaskExecutor(h.store, h.manager), config)
    await runner._tick()
    await asyncio.wait_for(entered.wait(), 5)
    deletion = asyncio.create_task(runner.delete_routine(routine.id))
    shutdown = None
    try:
        await asyncio.wait_for(cleaning.wait(), 5)
        shutdown = asyncio.create_task(runner.stop())
        await asyncio.sleep(0.05)
        assert not deletion.done()
        assert not shutdown.done()
        assert h.store.get_run(run.id) is not None
    finally:
        release.set()
        conversations = await asyncio.wait_for(deletion, 5)
        if shutdown is not None:
            await asyncio.wait_for(shutdown, 5)
    assert len(conversations) == 1
    assert conversations[0] in h.exited_conversations
    assert h.store.get_routine(routine.id) is None
