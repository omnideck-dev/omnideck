"""Exercise the public agent core directly with the real FakeProvider protocol."""

import asyncio
from copy import deepcopy

import pytest

from agent_core import AgentExecutor, ExecutionContext
from agent_core.agent import Agent
from agent_core.agent_capabilities import AgentCapabilities, get_active_agent_capabilities
from agent_core.control import ExecutionControl, _current_control
from agent_core.turn._models import _current_execution
from agent_core.context import ConversationHistory
from agent_core.events import AgentEvent, AgentStartedPayload, UserMessagePayload, publish_event
from agent_core.hooks import LoadedSkillHook, NudgeHook
from providers._fake import FakeProvider
from agent_core.skills._registry import Skill
from tests.e2e._protocol import call_tool, say


class RecordingProvider(FakeProvider):
    """Record requests at the model boundary, retaining FakeProvider behavior."""

    def __init__(self):
        self.requests = []

    async def chat_stream(self, **kwargs):
        self.requests.append(
            {
                **deepcopy(kwargs),
                "tools": [tool.__name__ for tool in kwargs.get("tools", [])],
            }
        )
        async for chunk in super().chat_stream(**kwargs):
            yield chunk


def prepare(prompt, capabilities=None, *, identity="standalone"):
    agent = Agent(name=identity, description="", instruction="system", provider="fake", model="fake-model", options={})
    capabilities = capabilities or AgentCapabilities([])
    history = ConversationHistory(system_message=agent.instruction, conversation_id=identity, agent_id=identity)
    context = ExecutionContext(
        execution_id=identity,
        run_id=identity,
        conversation_id=identity,
        event_sink=history,
        control=ExecutionControl(),
    )
    # A caller supplies accepted input and lifecycle; the executor owns only
    # model/tool iterations. These are input events, not fabricated responses.
    with context.bind(agent.name, capabilities):
        publish_event(
            AgentEvent(
                payload=AgentStartedPayload(
                    type="agent_started",
                    agent_id=identity,
                    agent_name=identity,
                )
            )
        )
        publish_event(AgentEvent(payload=UserMessagePayload(type="user_message", content=prompt)))
    return dict(agent=agent, capabilities=capabilities, history=history, context=context)


async def test_standalone_executor_loads_tools_and_guidance_for_next_request():
    calls = []

    async def echo(value: str) -> str:
        """Echo a value."""
        calls.append(value)
        return value

    async def enable_skill() -> str:
        """Enable echo and its guidance for subsequent model calls."""
        get_active_agent_capabilities().load(
            Skill(id="echo", name="Echo", description="Echo values", prompt="Echo guidance", tools=[echo])
        )
        return "enabled"

    inputs = prepare(
        call_tool("enable_skill") + call_tool("echo", value="verified") + say("done"), AgentCapabilities([enable_skill])
    )
    provider = RecordingProvider()
    result = await AgentExecutor().execute(**inputs, provider=provider, hooks=[LoadedSkillHook()])

    assert result.status == "success"
    assert result.output == "done"
    assert result.finish_reason is not None
    assert result.usage.prompt_tokens == 0  # FakeProvider reports no token usage.
    assert calls == ["verified"]
    assert "echo" not in provider.requests[0]["tools"]
    assert "echo" in provider.requests[1]["tools"]
    assert "Echo guidance" in provider.requests[1]["messages"][0]["content"]
    assert inputs["capabilities"].loaded_skill_ids == {"echo"}
    assert get_active_agent_capabilities() is None


async def test_same_executor_keeps_concurrent_capabilities_control_and_events_isolated():
    executor = AgentExecutor()
    reached = asyncio.Event()
    release = asyncio.Event()

    async def pause() -> str:
        """Wait for the other execution to finish."""
        reached.set()
        await release.wait()
        return "released"

    first = prepare(call_tool("pause") + say("first"), AgentCapabilities([pause]), identity="first")
    second = prepare(say("second"), identity="second")
    first_provider, second_provider = RecordingProvider(), RecordingProvider()
    first_task = asyncio.create_task(executor.execute(**first, provider=first_provider))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        first["context"].control.stop()
        other = await executor.execute(**second, provider=second_provider)
    finally:
        release.set()
    stopped = await asyncio.wait_for(first_task, 5)

    assert stopped.status == "stopped"
    assert other.status == "success" and other.output == "second"
    assert second_provider.requests[0]["tools"] == []
    assert all("first" not in str(m) for m in second_provider.requests[0]["messages"])
    assert not second["context"].control.stop_event.is_set()
    assert get_active_agent_capabilities() is None


async def test_nudge_uses_supplied_inbox_and_is_consumed_once():
    inputs = prepare(say("original"))
    inputs["context"].control.nudge(say("nudged"))
    provider = RecordingProvider()
    result = await AgentExecutor().execute(**inputs, provider=provider, hooks=[NudgeHook()])
    assert result.status == "success" and result.output == "nudged"
    assert inputs["context"].control.drain_nudges() == []
    assert any("nudged" in m.get("content", "") for m in provider.requests[0]["messages"])


async def test_stop_before_execution_makes_no_provider_request():
    inputs = prepare(say("never"))
    inputs["context"].control.stop()
    provider = RecordingProvider()
    result = await AgentExecutor().execute(**inputs, provider=provider)
    assert result.status == "stopped" and result.output is None
    assert provider.requests == []
    assert result.usage.prompt_tokens == 0


async def test_provider_failure_returns_partial_output_and_typed_error():
    inputs = prepare("<<PROVIDERFAIL mid>>quota exhausted<<END>>")
    provider = RecordingProvider()
    result = await AgentExecutor().execute(**inputs, provider=provider)
    assert result.status == "error"
    assert result.error and "quota exhausted" in result.error
    assert result.output
    assert any(m.get("role") == "assistant" and m.get("content") == result.output for m in inputs["history"].messages)


async def test_cancellation_restores_scoped_capabilities():
    reached = asyncio.Event()

    async def pause() -> str:
        """Block until cancelled by the caller."""
        reached.set()
        await asyncio.Event().wait()
        return "unreachable"

    inputs = prepare(call_tool("pause"), AgentCapabilities([pause]))

    async def execute_and_verify_cleanup():
        try:
            return await AgentExecutor().execute(**inputs, provider=FakeProvider())
        finally:
            assert get_active_agent_capabilities() is None
            assert _current_control.get() is None
            assert _current_execution.get() is None

    task = asyncio.create_task(execute_and_verify_cleanup())
    await asyncio.wait_for(reached.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert get_active_agent_capabilities() is None
