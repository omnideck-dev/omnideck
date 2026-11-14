"""send() queues a message for a working agent and starts a run otherwise."""

import asyncio

import pytest

from agent_core.events import AgentEvent, UserMessagePayload
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, AttachmentsWhileRunningError, QueuedMessage, RunAttachment


class WorkingRunner:
    """Keeps the root agent working until released, then reads its queue once if told to."""

    def __init__(self, outcome="success"):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.read_before_end = False
        self.outcome = outcome
        self.runs = 0

    async def run(self, request, session):
        self.runs += 1
        self.started.set()
        await self.release.wait()
        if self.read_before_end:
            for message in session.root_context.control.drain_nudges():
                session.add_event(AgentEvent(payload=message))
        if self.outcome == "error":
            raise RuntimeError("provider failed")
        return ExecutionResult("success")


def request(message="hello", attachments=None):
    return AgentRunRequest("chat", message, attachments, "assistant")


def payloads(handle, kind):
    return [record.event.payload for record in handle._session.records if record.event.payload.type == kind]


async def test_send_starts_a_run_when_the_agent_is_idle_and_queues_while_it_works():
    runner = WorkingRunner()
    runtime = AgentRuntime(runner)
    try:
        handle = await runtime.send(request())
        await runner.started.wait()
        queued = await runtime.send(request("also check the weather"))
        assert isinstance(queued, QueuedMessage)
        assert queued.run_id == handle.run_id
        assert runner.runs == 1
        (event,) = payloads(handle, "nudge_queued")
        assert (event.nudge_id, event.content, event.context) == (queued.nudge_id, "also check the weather", [])
        runner.read_before_end = True
        runner.release.set()
        await handle.wait()
        read = [p for p in payloads(handle, "user_message") if p.nudge_id == queued.nudge_id]
        assert len(read) == 1 and read[0].is_nudge
        assert payloads(handle, "nudge_removed") == []
    finally:
        runner.release.set()
        await runtime.close()


async def test_send_with_files_while_the_agent_works_is_refused():
    runner = WorkingRunner()
    runtime = AgentRuntime(runner)
    try:
        handle = await runtime.send(request())
        await runner.started.wait()
        files = [RunAttachment(base64_encoded="aGk=", content_type="text/plain", filename="a.txt")]
        with pytest.raises(AttachmentsWhileRunningError, match="Files can be sent after the agent finishes."):
            await runtime.send(request("see attached", files))
        assert payloads(handle, "nudge_queued") == []
    finally:
        runner.release.set()
        await runtime.close()


async def test_remove_nudge_works_before_the_agent_reads_it_and_fails_after():
    runner = WorkingRunner()
    runtime = AgentRuntime(runner)
    try:
        handle = await runtime.send(request())
        await runner.started.wait()
        removed = await runtime.send(request("never mind"))
        kept = await runtime.send(request("keep this"))
        assert handle.remove_nudge(removed.nudge_id)
        assert not handle.remove_nudge(removed.nudge_id)
        (event,) = payloads(handle, "nudge_removed")
        assert (event.nudge_id, event.reason) == (removed.nudge_id, "removed")
        runner.read_before_end = True
        runner.release.set()
        await handle.wait()
        assert not handle.remove_nudge(kept.nudge_id)
        assert [p.content for p in payloads(handle, "user_message")] == ["keep this"]
    finally:
        runner.release.set()
        await runtime.close()


@pytest.mark.parametrize("ending", ["stop", "error"])
async def test_run_end_returns_every_unread_message(ending):
    runner = WorkingRunner(outcome="error" if ending == "error" else "success")
    runtime = AgentRuntime(runner)
    try:
        handle = await runtime.send(request())
        await runner.started.wait()
        first = await runtime.send(request("one"))
        second = await runtime.send(request("two"))
        if ending == "stop":
            handle.cancel()
        else:
            runner.release.set()
        result = await handle.wait()
        assert result.status == ("stopped" if ending == "stop" else "error")
        returned = payloads(handle, "nudge_removed")
        assert [(p.nudge_id, p.reason) for p in returned] == [(first.nudge_id, "returned"), (second.nudge_id, "returned")]
        types = [record.event.payload.type for record in handle._session.records]
        assert types[-1] == "turn_end"
    finally:
        runner.release.set()
        await runtime.close()


async def test_send_while_the_run_is_ending_starts_a_new_run():
    runner = WorkingRunner()
    runtime = AgentRuntime(runner)
    try:
        first = await runtime.send(request())
        await runner.started.wait()
        first.stop()
        second = runtime.send(request("next"))
        runner.release.set()
        started = await asyncio.wait_for(second, 5)
        assert not isinstance(started, QueuedMessage)
        assert started.run_id != first.run_id
        await started.wait()
        assert runner.runs == 2
    finally:
        runner.release.set()
        await runtime.close()


async def test_observe_events_sees_every_published_event_until_unsubscribed():
    runner = WorkingRunner()
    runner.release.set()
    runtime = AgentRuntime(runner)
    seen = []
    stop = runtime.observe_events(lambda conversation_id, event: seen.append((conversation_id, event.payload.type)))
    try:
        await (await runtime.send(request())).wait()
        assert ("chat", "turn_end") in seen
        stop()
        count = len(seen)
        await (await runtime.send(request())).wait()
        assert len(seen) == count
    finally:
        await runtime.close()


async def test_a_failing_event_observer_does_not_break_the_run():
    runner = WorkingRunner()
    runner.release.set()
    runtime = AgentRuntime(runner)

    def broken(_conversation_id, _event):
        raise RuntimeError("observer bug")

    runtime.observe_events(broken)
    try:
        assert (await (await runtime.send(request())).wait()).status == "success"
    finally:
        await runtime.close()


def test_user_message_nudge_id_defaults_to_none():
    assert UserMessagePayload(type="user_message", content="hi").nudge_id is None
