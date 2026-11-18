"""Activity uses existing run ownership and results without retaining past completions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunSession
from server import _run_activity
from server._agent_runtime import AGENT_RUNTIME_KEY
from server._run_activity import activity_events


class Runner:
    def __init__(self) -> None:
        self.sessions: dict[str, RunSession] = {}
        self.release: dict[str, asyncio.Event] = {}

    async def run(self, request: AgentRunRequest, session: RunSession) -> ExecutionResult:
        self.sessions[request.conversation_id] = session
        release = self.release.setdefault(request.conversation_id, asyncio.Event())
        await release.wait()
        return ExecutionResult(request.message)


async def message(feed):
    item = await anext(feed)
    return item.model_dump(mode='json') if item is not None else None


def request(cid: str, outcome: str = 'success') -> AgentRunRequest:
    return AgentRunRequest(cid, outcome, None, None)


async def test_activity_snapshot_starts_and_results_cover_independent_runs() -> None:
    runner = Runner()
    runtime = AgentRuntime(runner)
    first = await runtime.start(request('one'))
    feed = activity_events(runtime)
    try:
        assert await message(feed) == {'type': 'run_snapshot', 'runs': [
            {'conversation_id': 'one', 'run_id': first.run_id},
        ]}
        second = await runtime.start(request('two', 'error'))
        assert await message(feed) == {'type': 'run_started', 'runs': [
            {'conversation_id': 'two', 'run_id': second.run_id},
        ]}
        await asyncio.sleep(0)
        runner.release['two'].set()
        assert await asyncio.wait_for(message(feed), 2) == {'type': 'run_finished', 'runs': [
            {'conversation_id': 'two', 'run_id': second.run_id},
        ]}
        assert (await second.wait()).status == 'error'
        assert runtime.active_for_conversation('one') is not None
        runner.release['one'].set()
        assert (await asyncio.wait_for(message(feed), 2))['runs'][0]['run_id'] == first.run_id
    finally:
        await feed.aclose()
        await runtime.close()


async def test_activity_disconnect_does_not_stop_runs_and_reconnect_has_no_history() -> None:
    runner = Runner()
    runtime = AgentRuntime(runner)
    feed = activity_events(runtime)
    try:
        assert await message(feed) == {'type': 'run_snapshot', 'runs': []}
        first = await runtime.start(request('one'))
        await message(feed)
        await feed.aclose()
        assert runtime.active_for_conversation('one') is not None
        assert not runner.sessions['one'].stop_event.is_set()
        reconnect = activity_events(runtime)
        assert (await message(reconnect))['runs'][0]['run_id'] == first.run_id
        runner.release['one'].set()
        await first.wait()
        await reconnect.aclose()
        fresh = activity_events(runtime)
        assert await message(fresh) == {'type': 'run_snapshot', 'runs': []}
        await fresh.aclose()
    finally:
        await feed.aclose()
        await runtime.close()


async def test_activity_reports_stop_before_first_agent_event() -> None:
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime)
    try:
        await message(feed)
        handle = await runtime.start(request('one'))
        handle.stop()
        assert (await message(feed))['type'] == 'run_started'
        assert (await asyncio.wait_for(message(feed), 2))['type'] == 'run_finished'
        assert (await handle.wait()).status == 'stopped'
    finally:
        await feed.aclose()
        await runtime.close()


async def test_run_observation_failure_cannot_fail_start_and_unsubscribes() -> None:
    runtime = AgentRuntime(Runner())
    seen = []

    def broken(handle):
        seen.append(handle.conversation_id)
        raise ValueError('observer failure')

    try:
        with runtime.observe_runs(broken) as active:
            assert active == ()
            handle = await runtime.start(request('one'))
        second = await runtime.start(request('two'))
        assert seen == ['one']
        handle.stop()
        second.stop()
        await handle.wait()
        await second.wait()
    finally:
        await runtime.close()


async def test_activity_overflow_bounds_backlog_and_reconnects_without_stopping_runs(monkeypatch) -> None:
    monkeypatch.setattr(_run_activity, '_ACTIVITY_QUEUE_LIMIT', 2)
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime)
    try:
        original = await runtime.start(request('original'))
        await message(feed)
        # Simulate a consumer paused in a socket write while runs are accepted.
        for index in range(10):
            handle = await runtime.start(request(f'burst-{index}'))
            handle.stop()
            await handle.wait()
        await asyncio.sleep(0)
        assert feed.ag_frame.f_locals['queue'].qsize() == 2
        with pytest.raises(_run_activity._ActivityBacklogExceeded):
            await message(feed)
        assert not runtime._run_observers
        assert runtime.active_for_conversation('original') is not None
        assert not original._session.stop_event.is_set()
        reconnect = activity_events(runtime)
        try:
            assert await message(reconnect) == {'type': 'run_snapshot', 'runs': [
                {'conversation_id': 'original', 'run_id': original.run_id},
            ]}
        finally:
            await reconnect.aclose()
    finally:
        await feed.aclose()
        await runtime.close()


@pytest.mark.parametrize('failure', ['stalled_write', 'overflow'])
async def test_activity_failure_closes_socket_and_observers_without_stopping_run(monkeypatch, failure) -> None:
    monkeypatch.setattr(_run_activity, '_ACTIVITY_WRITE_TIMEOUT_SECONDS', 0.01)
    monkeypatch.setattr(_run_activity, '_ACTIVITY_QUEUE_LIMIT', 2)
    runtime = AgentRuntime(Runner())
    transport = Mock()
    response = Mock()
    write_cancelled = asyncio.Event()

    async def prepare(request):
        return None

    async def write(frame):
        if failure == 'overflow':
            for index in range(4):
                handle = await runtime.start(request(f'burst-{index}'))
                handle.stop()
            return
        try:
            await asyncio.Event().wait()
        finally:
            write_cancelled.set()

    response.prepare = prepare
    response.write = write
    monkeypatch.setattr(_run_activity.web, 'StreamResponse', lambda **kwargs: response)
    http_request = SimpleNamespace(app={AGENT_RUNTIME_KEY: runtime}, transport=transport)
    try:
        handle = await runtime.start(request('still-running'))
        assert await asyncio.wait_for(_run_activity.run_activity_handler(http_request), 1) is response
        if failure == 'stalled_write':
            assert write_cancelled.is_set()
        response.force_close.assert_called_once()
        transport.close.assert_called_once()
        assert not runtime._run_observers
        assert runtime.active_for_conversation('still-running') is not None
        assert not handle._session.stop_event.is_set()
    finally:
        await runtime.close()


@pytest.fixture
def goal_feed(tmp_path):
    from goals import GoalStore
    from server._goals import GoalActivityFeed

    enabled = {'value': True}
    store = GoalStore(tmp_path / 'conversations')
    return store, GoalActivityFeed(store, lambda: enabled['value']), enabled


async def test_first_messages_are_run_snapshot_then_goal_snapshot(goal_feed) -> None:
    store, goals, _enabled = goal_feed
    goal = store.create('chat', 'Plan the reunion')
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [goals])
    try:
        assert (await message(feed))['type'] == 'run_snapshot'
        snapshot = await message(feed)
        assert snapshot['type'] == 'goal_snapshot'
        assert [item['id'] for item in snapshot['goals']] == [goal.id]
    finally:
        await feed.aclose()
        await runtime.close()


async def test_goal_saves_send_goal_changed_with_the_whole_goal(goal_feed) -> None:
    store, goals, _enabled = goal_feed
    goal = store.create('chat', 'Plan the reunion')
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [goals])
    try:
        await message(feed)
        await message(feed)
        store.update(goal.id, goal.revision, summary='Booked the pavilion.')
        changed = await asyncio.wait_for(message(feed), 2)
        assert changed['type'] == 'goal_changed' and changed['conversation_id'] == 'chat'
        assert changed['goal']['summary'] == 'Booked the pavilion.' and changed['goal']['plan'] == []
        store.claim_for_turn(goal.id, 'turn')
        store.bind_run(goal.id, 'turn', 'run-7')
        claimed = await asyncio.wait_for(message(feed), 2)
        bound = await asyncio.wait_for(message(feed), 2)
        assert claimed['goal']['claim'] == {'id': 'turn', 'wake_id': None}
        assert bound['goal']['last_run_id'] == 'run-7'
    finally:
        await feed.aclose()
        await runtime.close()


async def test_nothing_goal_related_is_sent_while_goals_are_off(goal_feed) -> None:
    store, goals, enabled = goal_feed
    goal = store.create('chat', 'Plan the reunion')
    enabled['value'] = False
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [goals])
    try:
        assert (await message(feed))['type'] == 'run_snapshot'
        store.update(goal.id, goal.revision, summary='Hidden.')
        started = await runtime.start(request('one'))
        assert (await asyncio.wait_for(message(feed), 2))['type'] == 'run_started'
        started.stop()
    finally:
        await feed.aclose()
        await runtime.close()


async def test_turning_goals_on_sends_open_streams_the_goals(goal_feed) -> None:
    store, goals, enabled = goal_feed
    goal = store.create('chat', 'Plan the reunion')
    enabled['value'] = False
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [goals])
    try:
        assert (await message(feed))['type'] == 'run_snapshot'
        enabled['value'] = True
        goals.resend_snapshot()
        snapshot = await asyncio.wait_for(message(feed), 2)
        assert snapshot['type'] == 'goal_snapshot'
        assert [item['id'] for item in snapshot['goals']] == [goal.id]
    finally:
        await feed.aclose()
        await runtime.close()


def test_resend_reaches_no_stream_after_it_unsubscribes(goal_feed) -> None:
    store, goals, _enabled = goal_feed
    store.create('chat', 'Plan the reunion')
    sent = []
    unsubscribe = goals.subscribe(lambda item: sent.append(item) or True)
    goals.resend_snapshot()
    unsubscribe()
    goals.resend_snapshot()
    assert [item.type for item in sent] == ['goal_snapshot']


async def test_disconnect_unsubscribes_the_goal_feed(goal_feed) -> None:
    store, goals, _enabled = goal_feed
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime, [goals])
    try:
        await message(feed)
        await message(feed)
        assert len(store._observers) == 1
    finally:
        await feed.aclose()
        await runtime.close()
    assert store._observers == []


def test_goal_snapshot_reads_no_goal_files(goal_feed, monkeypatch) -> None:
    from pathlib import Path

    store, goals, _enabled = goal_feed
    store.create('chat', 'Plan the reunion')
    store.load()

    def refuse(*_args, **_kwargs):
        raise AssertionError('The snapshot must not read goal files')

    monkeypatch.setattr(Path, 'read_text', refuse)
    assert len(goals.snapshot().goals) == 1
