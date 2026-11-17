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


def request(cid: str, outcome: str = 'success') -> AgentRunRequest:
    return AgentRunRequest(cid, outcome, None, None)


async def test_activity_snapshot_starts_and_results_cover_independent_runs() -> None:
    runner = Runner()
    runtime = AgentRuntime(runner)
    first = await runtime.start(request('one'))
    feed = activity_events(runtime)
    try:
        assert await anext(feed) == {'type': 'snapshot', 'runs': [
            {'conversation_id': 'one', 'run_id': first.run_id},
        ]}
        second = await runtime.start(request('two', 'error'))
        assert await anext(feed) == {'type': 'started', 'runs': [
            {'conversation_id': 'two', 'run_id': second.run_id},
        ]}
        await asyncio.sleep(0)
        runner.release['two'].set()
        assert await asyncio.wait_for(anext(feed), 2) == {'type': 'finished', 'runs': [
            {'conversation_id': 'two', 'run_id': second.run_id},
        ]}
        assert (await second.wait()).status == 'error'
        assert runtime.active_for_conversation('one') is not None
        runner.release['one'].set()
        assert (await asyncio.wait_for(anext(feed), 2))['runs'][0]['run_id'] == first.run_id
    finally:
        await feed.aclose()
        await runtime.close()


async def test_activity_disconnect_does_not_stop_runs_and_reconnect_has_no_history() -> None:
    runner = Runner()
    runtime = AgentRuntime(runner)
    feed = activity_events(runtime)
    try:
        assert await anext(feed) == {'type': 'snapshot', 'runs': []}
        first = await runtime.start(request('one'))
        await anext(feed)
        await feed.aclose()
        assert runtime.active_for_conversation('one') is not None
        assert not runner.sessions['one'].stop_event.is_set()
        reconnect = activity_events(runtime)
        assert (await anext(reconnect))['runs'][0]['run_id'] == first.run_id
        runner.release['one'].set()
        await first.wait()
        await reconnect.aclose()
        fresh = activity_events(runtime)
        assert await anext(fresh) == {'type': 'snapshot', 'runs': []}
        await fresh.aclose()
    finally:
        await feed.aclose()
        await runtime.close()


async def test_activity_reports_stop_before_first_agent_event() -> None:
    runtime = AgentRuntime(Runner())
    feed = activity_events(runtime)
    try:
        await anext(feed)
        handle = await runtime.start(request('one'))
        handle.stop()
        assert (await anext(feed))['type'] == 'started'
        assert (await asyncio.wait_for(anext(feed), 2))['type'] == 'finished'
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
        await anext(feed)
        # Simulate a consumer paused in a socket write while runs are accepted.
        for index in range(10):
            handle = await runtime.start(request(f'burst-{index}'))
            handle.stop()
            await handle.wait()
        await asyncio.sleep(0)
        assert feed.ag_frame.f_locals['queue'].qsize() == 2
        with pytest.raises(_run_activity._ActivityBacklogExceeded):
            await anext(feed)
        assert not runtime._run_observers
        assert runtime.active_for_conversation('original') is not None
        assert not original._session.stop_event.is_set()
        reconnect = activity_events(runtime)
        try:
            assert await anext(reconnect) == {'type': 'snapshot', 'runs': [
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
