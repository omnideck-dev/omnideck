"""Tests that tool loop publishes AgentEvent events via the dispatcher.

Covers:
- Emission of content/thinking events after a model response
- Emission of tool_call event before executing a tool
"""

from __future__ import annotations

from typing import Any, List

import pytest
from tests.unit.agent_core._execution_inputs import execution_inputs

from agent_core.context import ConversationHistory
from agent_core.events import (
    AgentEvent,
    ContentPayload,
    IterationPayload,
    ToolCallPayload,
    ToolResultPayload,
    agent_span,
    reset_current_conversation,
    set_current_conversation,
)
from agent_core.agent_capabilities import AgentCapabilities
from agent_core.providers._models import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolCallFunction
from agent_core.turn import AgentExecutor
from agent_core.agent import Agent


def _make_response(
    content: str | None = None,
    thinking: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> ChatResponse:
    tc_list = None
    if tool_calls:
        tc_list = [
            ToolCall(function=ToolCallFunction(name=tc["name"], arguments=tc.get("arguments", {})))
            for tc in tool_calls
        ]
    return ChatResponse(
        message=ChatMessage(content=content, thinking=thinking, tool_calls=tc_list),
        usage=TokenUsage(),
    )


class _ProviderScript:
    """Scripted fake provider that returns queued responses."""

    def __init__(self, responses: list[ChatResponse]):
        self._responses: list[ChatResponse] = list(responses)

    async def chat(self, **_: Any) -> ChatResponse:
        if not self._responses:
            return _make_response(content="done")
        return self._responses.pop(0)

    async def chat_stream(self, **kwargs: Any):
        yield await self.chat(**kwargs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_loop_emits_model_and_tool_call_events(monkeypatch):
    # Arrange: scripted responses -> first triggers a tool call, then finishes
    resp1 = _make_response(
        content="partial",
        thinking="t",
        tool_calls=[{"name": "echo_tool", "arguments": {"x": 1}}],
    )
    resp2 = _make_response(content="done")


    # Patch provider used by the module under test
    provider = _ProviderScript([resp1, resp2])

    # Minimal tool implementation that will be found by name
    def echo_tool(x: int) -> dict[str, int]:  # noqa: D401 - simple dummy
        return {"x": x}

    captured: List[AgentEvent] = []

    async def _handler(evt: AgentEvent) -> None:
        captured.append(evt)

    # Pass conversation_id so the autouse conftest bridge skips this
    # history — we're driving the new conversation-owned path directly.
    history = ConversationHistory(
        [{"role": "system", "content": "ctx"}],
        conversation_id="conv-tool-loop",
    )

    # Act: run the tool loop inside a turn scope; drain is automatic on exit
    agent = Agent(
        name="Test Agent",
        description="desc",
        instruction="ctx",
        provider="ollama",
        model="dummy",
        options={},

    )

    history.subscribe(_handler)
    conv_token = set_current_conversation(history)
    try:
        async with agent_span("Test", agent_capabilities=AgentCapabilities([echo_tool])):
            execution = await AgentExecutor().execute(history=history, agent=agent, **execution_inputs(provider, 1))
            execution.raise_for_status()
    finally:
        reset_current_conversation(conv_token)
        await history.drain_observers()

    # Assert: at least two events: one model output and one tool_call
    assert any(
        isinstance(e.payload, ContentPayload) and e.payload.content == "partial" and e.payload.thinking == "t"
        for e in captured
    )
    tool_events = [e.payload for e in captured if isinstance(e.payload, ToolCallPayload)]
    assert any(
        ev.type == "tool_call" and ev.name == "echo_tool"
        for ev in tool_events
    )
    # The tool_call event carries the (stringified) arguments.
    echo_event = next(ev for ev in tool_events if ev.name == "echo_tool")
    assert echo_event.arguments == {"x": "1"}
    # Ensure order: model event occurs before tool_call for the same cycle
    first_model_idx = next(
        i for i, e in enumerate(captured)
        if isinstance(e.payload, ContentPayload) and e.payload.content == "partial"
    )
    first_tool_idx = next(
        i for i, e in enumerate(captured) if isinstance(e.payload, ToolCallPayload)
    )
    assert first_model_idx <= first_tool_idx
    # Verify context metadata: tool loop runs in root context (depth 0) when invoked directly
    assert all(e.depth == 0 for e in captured)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_loop_emits_iteration_and_tool_result_events(monkeypatch):
    """AgentExecutor.execute should emit one IterationPayload per iteration (bundling thinking,
    content, tool_calls) and one ToolResultPayload per tool that runs."""
    resp1 = _make_response(
        content="picking a tool",
        thinking="reasoning",
        tool_calls=[{"name": "echo_tool", "arguments": {"x": 1}}],
    )
    resp2 = _make_response(content="done")

    provider = _ProviderScript([resp1, resp2])

    def echo_tool(x: int) -> dict[str, int]:
        return {"x": x}

    captured: List[AgentEvent] = []

    async def _handler(evt: AgentEvent) -> None:
        captured.append(evt)

    history = ConversationHistory(
        [{"role": "system", "content": "ctx"}],
        conversation_id="conv-iter-tool-results",
    )
    agent = Agent(
        name="Test Agent",
        description="desc",
        instruction="ctx",
        provider="ollama",
        model="dummy",
        options={},

    )

    history.subscribe(_handler)
    conv_token = set_current_conversation(history)
    try:
        async with agent_span("Test", agent_capabilities=AgentCapabilities([echo_tool])):
            execution = await AgentExecutor().execute(history=history, agent=agent, **execution_inputs(provider, 1))
            execution.raise_for_status()
    finally:
        reset_current_conversation(conv_token)
        await history.drain_observers()

    iterations = [e.payload for e in captured if isinstance(e.payload, IterationPayload)]
    tool_results = [e.payload for e in captured if isinstance(e.payload, ToolResultPayload)]

    # Two model calls -> two iteration events with monotonic indices.
    assert [it.iteration_index for it in iterations] == [0, 1]

    first, second = iterations
    assert first.content == "picking a tool"
    assert first.thinking == "reasoning"
    assert len(first.tool_calls) == 1
    tc = first.tool_calls[0]
    assert tc.name == "echo_tool"
    assert tc.arguments == {"x": 1}

    assert second.content == "done"
    assert second.tool_calls == []

    # One tool ran -> one tool_result event tying back to the iteration's tool call.
    assert len(tool_results) == 1
    tr = tool_results[0]
    assert tr.tool_name == "echo_tool"
    assert tr.tool_call_id == tc.id
    assert "x" in tr.content  # str() of {"x": 1}

    # Order: first iteration → tool_result → second iteration.
    iter_idx = [i for i, e in enumerate(captured) if isinstance(e.payload, IterationPayload)]
    tr_idx = next(i for i, e in enumerate(captured) if isinstance(e.payload, ToolResultPayload))
    assert iter_idx[0] < tr_idx < iter_idx[1]
