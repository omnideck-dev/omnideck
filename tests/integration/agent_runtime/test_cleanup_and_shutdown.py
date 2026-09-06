"""Session cleanup and process shutdown with real FakeProvider execution trees."""

import asyncio

import pytest

from agent_core.context import ConversationHistory
from agent_core.control import StopRequestedError
from agent_core.turn import get_execution_context
from agent_runtime import AgentRunRequest, AgentRuntimeClosedError, RunConflictError, RunPolicy
from conversations import load_events_jsonl, register_conversation_exit_hook
from conversations import _cache
from providers._fake import FakeProvider
from tasks import TaskExecutor
from tests.e2e._protocol import call_tool, say, spawn


@pytest.fixture(autouse=True)
def fake_provider(harness, monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr("agent_runtime._factory.get_provider", lambda _: provider)


def _request(conversation="cleanup", *, lifetime="cached", message=None, profile="leaf"):
    return AgentRunRequest(
        conversation_id=conversation,
        message=message or say("completed"),
        attachments=None,
        profile_id=profile,
        policy=RunPolicy(conversation_lifetime=lifetime),
    )


def _assert_released(runtime, handle):
    assert runtime.get(handle.run_id) is None
    assert runtime.active_for_conversation(handle.conversation_id) is None
    assert not _cache._leases[handle.conversation_id]
    assert handle._session.executions == {}
    history = handle._session.history
    if history is not None:
        assert history._observers == []
        assert not history._async_obs_tasks


@pytest.mark.parametrize("boundary", ["observer", "conversation"])
async def test_completion_and_terminal_event_wait_for_session_cleanup(harness, monkeypatch, boundary):
    h = harness
    h.profile()
    entered, release, finished, agent_finished = (asyncio.Event() for _ in range(4))

    if boundary == "observer":
        from agent_runtime._session import TerminalWriter

        original = TerminalWriter.handle_event

        async def delayed_writer(self, event):
            if event.payload.type == "user_message":
                entered.set()
                await release.wait()
                original(self, event)
                finished.set()
            else:
                original(self, event)

        monkeypatch.setattr(TerminalWriter, "handle_event", delayed_writer)
    else:

        async def delayed_conversation_cleanup(_conversation_id):
            entered.set()
            await release.wait()
            finished.set()

        register_conversation_exit_hook(delayed_conversation_cleanup)

    handle = await h.manager.start(_request(lifetime="run"))
    observed = []

    async def observe():
        async for record in handle.events():
            observed.append(record.event)
            if record.event.payload.type == "agent_completed":
                agent_finished.set()

    observer = asyncio.create_task(observe())
    waiter = asyncio.create_task(handle.wait())
    try:
        await asyncio.wait_for(asyncio.gather(entered.wait(), agent_finished.wait()), 5)
        assert not waiter.done()
        assert not observer.done()
        assert not finished.is_set()
        assert not any(event.payload.type == "turn_end" for event in observed)
        assert h.manager.active_for_conversation(handle.conversation_id) is not None
        with pytest.raises(RunConflictError):
            await h.manager.start(_request())
    finally:
        release.set()
        result, _ = await asyncio.wait_for(asyncio.gather(waiter, observer), 5)

    assert result.status == "success" and result.output == "completed"
    assert finished.is_set()
    assert observed[-1].payload.type == "turn_end"
    assert sum(event.payload.type == "turn_end" for event in observed) == 1
    assert h.exited_conversations == [handle.conversation_id]
    _assert_released(h.manager, handle)


@pytest.mark.parametrize("boundary", ["hydration", "writer_setup", "observer_drain", "conversation_cleanup"])
async def test_session_boundary_failure_releases_resources_and_allows_next_run(harness, monkeypatch, boundary):
    h = harness
    h.profile()
    failure = f"injected {boundary} failure"
    lifetime = "run" if boundary == "conversation_cleanup" else "cached"

    with monkeypatch.context() as patch:
        if boundary == "hydration":

            async def failed_load(_conversation_id):
                raise RuntimeError(failure)

            patch.setattr(h.manager, "_conversation_loader", failed_load)
        elif boundary == "writer_setup":

            def failed_writer(_conversation_id):
                raise RuntimeError(failure)

            patch.setattr("agent_runtime._session.TerminalWriter", failed_writer)
        elif boundary == "observer_drain":
            original = ConversationHistory.drain_observers

            async def failed_drain(history):
                await original(history)
                raise RuntimeError(failure)

            patch.setattr(ConversationHistory, "drain_observers", failed_drain)
        else:
            from agent_runtime._session import run_conversation_exit_hooks

            async def failed_cleanup(conversation_id):
                await run_conversation_exit_hooks(conversation_id)
                raise RuntimeError(failure)

            patch.setattr("agent_runtime._session.run_conversation_exit_hooks", failed_cleanup)

        handle = await h.manager.start(_request(lifetime=lifetime))
        result = await asyncio.wait_for(handle.wait(), 5)

    assert result.status == "error" and result.root.error == failure
    records = [record async for record in handle.events()]
    assert records[-1].event.payload.type == "turn_end"
    assert sum(record.event.payload.type == "turn_end" for record in records) == 1
    assert sum(record.event.payload.type == "error" for record in records) == 1
    _assert_released(h.manager, handle)

    # The failed run must leave neither a reservation nor old persistence observers.
    successor = await h.manager.start(_request())
    assert (await asyncio.wait_for(successor.wait(), 5)).output == "completed"
    _assert_released(h.manager, successor)
    events = load_events_jsonl(successor.conversation_id)
    assert len({event["id"] for event in events}) == len(events)


@pytest.mark.parametrize("mode", ["graceful", "forced"])
async def test_shutdown_stops_chat_and_routine_trees_and_waits_for_tools(harness, mode):
    h = harness
    entered = asyncio.Queue()
    tools = {}
    exited = set()
    cancelled = set()

    async def hold_until_shutdown() -> str:
        """Keep a leaf tool active until graceful stop or forced cancellation."""
        context = get_execution_context()
        tools[context.execution_id] = asyncio.current_task()
        entered.put_nowait(context)
        try:
            if mode == "graceful":
                await context.control.stop_event.wait()
                context.control.check_stop()
            else:
                await asyncio.Event().wait()
            return "unreachable"
        except asyncio.CancelledError:
            cancelled.add(context.execution_id)
            raise
        finally:
            exited.add(context.execution_id)

    h.skill("hold", hold_until_shutdown)
    h.profile("root", allow_spawn=True)
    h.profile("branch", allow_spawn=True)
    h.profile("leaf", skills=["hold"])
    prompt = spawn(
        spawn(call_tool("hold_until_shutdown") + say("unreachable leaf"), profile="leaf", name="LEAF")
        + say("unreachable branch"),
        profile="branch",
        name="BRANCH",
    ) + say("unreachable root")

    chat = await h.manager.start(_request("shutdown-chat", profile="root", message=prompt))
    routine = h.store.create_routine("shutdown", auto_run=False)
    task = h.store.create_task(routine.id, "nested agents", prompt, agent_profile="root")
    workflow = h.store.queue_run(routine.id)
    task_result = h.store.get_task_results(workflow.id)[0]
    owner = asyncio.create_task(TaskExecutor(h.store, h.manager).run(task_result, task))
    try:
        contexts = [await asyncio.wait_for(entered.get(), 5) for _ in range(2)]
        stored = h.store.get_task_results(workflow.id)[0]
        routine_handle = h.manager.get(stored.agent_run_id)
        assert routine_handle is not None
        assert {context.conversation_id for context in contexts} == {chat.conversation_id, stored.conversation_id}
        assert all(len(context.ancestors) == 2 for context in contexts)

        await asyncio.wait_for(h.manager.close(), 5)
        with pytest.raises(StopRequestedError):
            await asyncio.wait_for(owner, 5)

        all_agent_ids = set()
        for handle in (chat, routine_handle):
            result = await handle.wait()
            assert result.status == "stopped"
            assert len(result.executions) == 3
            assert all(execution.status == "stopped" for _, execution in result.executions)
            events = [record.event async for record in handle.events()]
            started = [event.payload.agent_id for event in events if event.payload.type == "agent_started"]
            completed = [event.payload for event in events if event.payload.type == "agent_completed"]
            assert len(started) == len(completed) == 3
            assert {event.agent_id for event in completed} == set(started)
            assert all(event.status == "stopped" for event in completed)
            assert events[-1].payload.type == "turn_end"
            assert sum(event.payload.type == "turn_end" for event in events) == 1
            all_agent_ids.update(started)
            _assert_released(h.manager, handle)

        assert set(h.exited_agents) == all_agent_ids and len(h.exited_agents) == 6
        assert h.exited_conversations == [stored.conversation_id]
        assert len(tools) == 2 and exited == set(tools)
        assert all(tool.done() for tool in tools.values())
        assert cancelled == (set(tools) if mode == "forced" else set())
        with pytest.raises(AgentRuntimeClosedError):
            await h.manager.start(_request("after-shutdown"))
    finally:
        # Preserve isolation even when an assertion fails before shutdown.
        chat.cancel()
        for session in tuple(h.manager._runs_by_id.values()):
            handle = h.manager.get(session.run_id)
            if handle is not None:
                handle.cancel()
                await handle.wait()
        await asyncio.gather(owner, return_exceptions=True)


async def test_forced_shutdown_awaits_cancellation_of_pending_event_writers(harness, monkeypatch):
    h = harness
    h.profile()
    from agent_runtime._session import TerminalWriter

    original = TerminalWriter.handle_event
    entered, cancelled = asyncio.Queue(), asyncio.Queue()
    release_cleanup = asyncio.Event()
    finished = set()
    pending_types = {"user_message", "agent_completed"}

    async def delayed_writer(self, event):
        if event.payload.type not in pending_types:
            original(self, event)
            return
        entered.put_nowait(event.payload.type)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.put_nowait(event.payload.type)
            raise
        finally:
            await release_cleanup.wait()
            finished.add(event.payload.type)

    monkeypatch.setattr(TerminalWriter, "handle_event", delayed_writer)
    handle = await h.manager.start(_request(lifetime="run"))
    stream = handle.events()
    close_task = None
    try:
        # Establish that execution finished and only session resources remain.
        async for record in stream:
            if record.event.payload.type == "agent_completed":
                break
        assert {await asyncio.wait_for(entered.get(), 5) for _ in range(2)} == pending_types
        close_task = asyncio.create_task(h.manager.close())
        assert {await asyncio.wait_for(cancelled.get(), 5) for _ in range(2)} == pending_types
        assert not close_task.done()
        assert not finished
        assert not any(record.event.payload.type == "turn_end" for record in handle._session.records)
        release_cleanup.set()
        await asyncio.wait_for(close_task, 5)
        assert finished == pending_types
        assert (await handle.wait()).status == "stopped"
        _assert_released(h.manager, handle)
        records = [record async for record in stream]
        assert records[-1].event.payload.type == "turn_end"
        assert sum(record.event.payload.type == "turn_end" for record in records) == 1
    finally:
        release_cleanup.set()
        history = handle._session.history
        if history is not None:
            pending = tuple(history._async_obs_tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if close_task is not None:
            await close_task
        await stream.aclose()
