"""Tests for the concrete application-level AgentRunner."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any
from agent_core.turn import ExecutionResult
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_runtime import AgentRuntime, AgentRunner, AgentRunRequest, RunAttachment
from agent_runtime import _runner as runner_module
from agent_runtime import _factory as factory_module
from agents._agent_profiles import AgentProfile
from conversations import load_events_jsonl
from agent_core.context import ConversationHistory
from agent_core.events import (
    AgentCompletedPayload,
    AgentEvent,
    AgentStartedPayload,
    ContentPayload,
    ErrorPayload,
    agent_span,
    publish_event,
)
from agent_core.turn import StopRequestedError, ToolLoopError


@pytest.fixture(autouse=True)
def _browser_runtime(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Keep agent-run tests isolated from the process Browser runtime."""
    monkeypatch.setattr(factory_module, "get_provider", lambda _: MagicMock())
    runtime = MagicMock()
    runtime.prepare_current_agent_browser = AsyncMock()
    @asynccontextmanager
    async def execution(**kwargs):
        await runtime.prepare_current_agent_browser(
            agent_profile_id=kwargs["agent_profile_id"], browser_profile_id=kwargs["browser_profile_id"],
        )
        yield

    runtime.execution = execution
    monkeypatch.setattr("agent_runtime._runtime.BrowserRuntime", lambda: runtime)
    monkeypatch.setattr(runner_module, "BrowserRuntime", lambda: runtime)
    runtime.close = AsyncMock()
    return runtime


def _request(conversation_id: str) -> AgentRunRequest:
    return AgentRunRequest(
        conversation_id=conversation_id,
        message="hello",
        attachments=None,
        profile_id="profile-1",
    )


async def _load_empty_history(
    conversation_id: str,
) -> ConversationHistory:
    return ConversationHistory(conversation_id=conversation_id)


async def _run(conversation_id: str) -> list[AgentEvent]:
    seen: list[AgentEvent] = []
    runtime = AgentRuntime()
    handle = await runtime.start(_request(conversation_id))
    seen = [record.event async for record in handle.events()]
    return seen


def _profile() -> AgentProfile:
    return AgentProfile(
        id="profile-1",
        name="Test",
        provider="ollama",
        model="test-model",
        system_prompt="test",
        skills=[],
    )


def test_attachments_produce_model_text_and_structured_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attachment setup retains both model paths and user-facing metadata."""
    paths = iter(["/virt/uploads/a.png", "/virt/uploads/b.csv"])
    monkeypatch.setattr(runner_module, "receive_attachment", lambda **_: next(paths))
    attachments = [
        RunAttachment(base64_encoded="aaaa", content_type="image/png", filename="a.png"),
        RunAttachment(base64_encoded="bbbb", content_type="text/csv", filename="b.csv"),
    ]

    text, attachments = runner_module._augment_message_with_attachments(
        "describe these",
        attachments,
    )

    assert "/virt/uploads/a.png" in text
    assert "/virt/uploads/b.csv" in text
    assert [item.filename for item in attachments] == ["a.png", "b.csv"]
    assert [item.path for item in attachments] == [
        "/virt/uploads/a.png",
        "/virt/uploads/b.csv",
    ]


def test_attachment_without_filename_falls_back_to_unnamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing browser filenames still produce useful attachment records."""
    monkeypatch.setattr(
        runner_module,
        "receive_attachment",
        lambda **_: "/virt/uploads/synth.png",
    )

    _text, attachments = runner_module._augment_message_with_attachments(
        "look",
        [RunAttachment(base64_encoded="aaaa", content_type="image/png", filename=None)],
    )

    assert attachments[0].filename == "unnamed"
    assert attachments[0].path == "/virt/uploads/synth.png"


async def test_manager_stop_before_concrete_runner_starts_skips_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manager-owned stop event reaches the runner's earliest checkpoint."""
    profile_lookups = 0

    def _unexpected_profile_lookup(_profile_id: str) -> None:
        nonlocal profile_lookups
        profile_lookups += 1

    monkeypatch.setattr(
        factory_module,
        "get_agent_profile",
        _unexpected_profile_lookup,
    )
    manager = AgentRuntime()

    info = await manager.start(_request("early-stop"))
    stream = info.events(after_seq=0)
    info.stop()

    records = [record async for record in stream]

    assert profile_lookups == 0
    assert [record.event.payload.type for record in records] == ["turn_end"]


async def test_setup_failure_is_persisted_and_ends_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallible setup runs inside turn_scope after persistence is subscribed."""
    conversation_id = "runner-setup-failure"

    def _explode(_profile_id: str) -> None:
        raise RuntimeError("profile store unavailable")

    monkeypatch.setattr(factory_module, "get_agent_profile", _explode)
    manager = AgentRuntime()
    info = await manager.start(_request(conversation_id))
    stream = info.events(after_seq=0)

    records = [record async for record in stream]
    persisted = load_events_jsonl(conversation_id)

    assert [record.event.payload.type for record in records] == [
        "error",
        "turn_end",
    ]
    # turn_end is deliberately transport-only; the canonical error is what
    # must survive conversation resume with the same stable event identity.
    assert [event["type"] for event in persisted] == ["error"]
    assert records[0].event.id == persisted[0]["id"]


async def test_tool_loop_failure_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ToolLoopError keeps its specific error and one scope-owned turn_end."""
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())

    async def _failing_execute(self, **_kwargs: Any) -> None:
        publish_event(
            AgentEvent(
                payload=ErrorPayload(
                    type="error",
                    message="usage limit reached",
                )
            )
        )
        raise ToolLoopError("usage limit reached")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _failing_execute)

    seen = await _run("runner-tool-failure")
    errors = [event for event in seen if event.payload.type == "error"]

    assert len(errors) == 1
    assert errors[0].payload.message == "usage limit reached"
    assert [event.payload.type for event in seen].count("turn_end") == 1


async def test_published_events_are_forwarded_once_and_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runner delivery includes nested lifecycle without duplicate events."""

    async def _fake_tool_loop(self, **_kwargs: Any) -> ExecutionResult:
        publish_event(
            AgentEvent(
                payload=ContentPayload(
                    type="content",
                    content="one",
                )
            )
        )
        await asyncio.sleep(0)
        async with agent_span("nested"):
            publish_event(
                AgentEvent(
                    payload=ContentPayload(
                        type="content",
                        content="secret",
                        thinking="hidden",
                    )
                )
            )

        return ExecutionResult("success")

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _fake_tool_loop)

    seen = await _run("runner-event-order")

    content = [(event.payload.content, event.payload.thinking) for event in seen if event.payload.type == "content"]
    assert content == [("one", None), ("secret", "hidden")]
    assert any(
        isinstance(event.payload, AgentStartedPayload) and event.payload.agent_name == "nested" for event in seen
    )
    completed_indexes = [index for index, event in enumerate(seen) if isinstance(event.payload, AgentCompletedPayload)]
    assert completed_indexes[-1] < len(seen) - 1
    assert seen[-1].payload.type == "turn_end"


async def test_runner_prepares_browser_from_agent_profile(
    monkeypatch: pytest.MonkeyPatch,
    _browser_runtime: MagicMock,
) -> None:
    """The application runner passes the selected profile to Browser runtime."""
    profile = _profile().model_copy(update={"browser_profile_id": "empty"})
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: profile)
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", AsyncMock(return_value=ExecutionResult("success")))

    await _run("runner-browser-profile")

    _browser_runtime.prepare_current_agent_browser.assert_awaited_once_with(
        agent_profile_id="profile-1",
        browser_profile_id="empty",
    )


async def test_stopped_root_lifecycle_precedes_turn_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped root records stopped completion before terminal delivery."""

    async def _stopped_tool_loop(self, **_kwargs: Any) -> None:
        publish_event(
            AgentEvent(
                payload=ContentPayload(
                    type="content",
                    content="partial",
                )
            )
        )
        raise StopRequestedError

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", _stopped_tool_loop)

    seen = await _run("runner-stop-order")
    root_completed = [
        event
        for event in seen
        if isinstance(event.payload, AgentCompletedPayload) and event.payload.agent_name == "TEST"
    ]

    assert root_completed[-1].payload.status == "stopped"
    assert seen.index(root_completed[-1]) < len(seen) - 1
    assert seen[-1].payload.type == "turn_end"


async def test_goal_tools_and_fresh_state_belong_only_to_owning_root(monkeypatch, tmp_path):
    from goals import GoalStore

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-goal-tools", "Organize household appointments", "profile-1")
    seen = []

    async def before_model(kwargs, iteration):
        for hook in kwargs["hooks"]:
            if hasattr(hook, "before_model"):
                await hook.before_model(kwargs["history"], iteration, "TEST")

    async def inspect_execution(**kwargs):
        context = kwargs["context"]
        tools = {tool.__name__: tool for tool in kwargs["capabilities"].tools}
        if context.parent_execution_id is not None:
            seen.append(("child", set(tools)))
            return ExecutionResult("success", output="Found available times")
        await before_model(kwargs, 1)
        assert "Read the goal before goal work" in kwargs["history"].messages[-1]["content"]
        assert json.loads(await tools["read_goal"]())["objective"] == "Organize household appointments"
        assert await tools["update_goal"](summary="Confirmed clinic opening times") == "Saved."
        await before_model(kwargs, 2)
        assert json.loads(await tools["read_goal"]())["summary"] == "Confirmed clinic opening times"
        await tools["spawn_agent"]("Find available times", "profile-1", "HELPER")
        result = await tools["choose_next_action"](
            action="complete", note="Booked both appointments.", outcome="Appointments arranged",
        )
        assert json.loads(result) == {"action": "complete", "outcome": "Appointments arranged"}
        # The ended goal stays readable while the owner writes its final response.
        await before_model(kwargs, 3)
        seen.append(("root", set(tools)))
        return ExecutionResult("success", output="Appointments arranged")

    async def execute(self, **kwargs):
        with kwargs["context"].bind("TEST", kwargs["capabilities"]):
            return await inspect_execution(**kwargs)

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = AgentRuntime(goal_store=store)
    try:
        handle = await runtime.start(_request(goal.conversation_id))
        result = await handle.wait()
        assert result.status == "success"
        child, root = dict(seen)["child"], dict(seen)["root"]
        assert not _GOAL_TOOLS & child
        assert _GOAL_TOOLS <= root
        saved = store.get(goal.id)
        assert saved.next.kind == "done"
        assert saved.claim is None and saved.last_run_id == handle.run_id
    finally:
        await runtime.close()


_GOAL_TOOLS = {"read_goal", "read_goal_history", "update_goal", "update_goal_questions", "choose_next_action"}


async def _goal_tools_for_chat_turn(monkeypatch, store, conversation_id, enabled=lambda: True):
    seen: list[set[str]] = []

    async def execute(self, **kwargs):
        seen.append({tool.__name__ for tool in kwargs["capabilities"].tools})
        for hook in kwargs["hooks"]:
            if hasattr(hook, "before_model"):
                await hook.before_model(kwargs["history"], 1, "TEST")
        return ExecutionResult("success", output="Here is where things stand.")

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = AgentRuntime(goal_store=store, goals_enabled=enabled)
    try:
        handle = await runtime.start(_request(conversation_id))
        assert (await handle.wait()).status == "success"
    finally:
        await runtime.close()
    return seen[0]


async def test_chat_turn_on_paused_goal_gets_all_goal_tools(monkeypatch, tmp_path):
    from goals import GoalStore

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-paused-goal", "Arrange appointments", "profile-1")
    store.pause(goal.id)
    tools = await _goal_tools_for_chat_turn(monkeypatch, store, goal.conversation_id)
    assert _GOAL_TOOLS <= tools
    saved = store.get(goal.id)
    assert saved.paused and saved.next == goal.next and saved.claim is None


async def test_chat_turn_on_error_goal_gets_all_goal_tools(monkeypatch, tmp_path):
    from goals import GoalStore

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-error-goal", "Arrange appointments", "profile-1")
    store.claim(goal.id, goal.next.id, "wake")
    failed = store.finish_run(goal.id, "wake", "run-0", "error", error="Provider unavailable")
    tools = await _goal_tools_for_chat_turn(monkeypatch, store, goal.conversation_id)
    assert _GOAL_TOOLS <= tools
    assert store.get(goal.id).next == failed.next


async def test_chat_turn_on_done_goal_gets_only_read_tools(monkeypatch, tmp_path):
    from goals import GoalStore
    from goals._models import GoalChoice

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-done-goal", "Arrange appointments", "profile-1")
    store.claim_for_turn(goal.id, "setup")
    store.choose(goal.id, GoalChoice.model_validate({"action": "complete", "note": "Done.", "outcome": "Booked."}),
                 claim_id="setup", expected_revision=goal.revision)
    done = store.finish_run(goal.id, "setup", "run-0", "success")
    tools = await _goal_tools_for_chat_turn(monkeypatch, store, goal.conversation_id)
    assert tools & _GOAL_TOOLS == {"read_goal", "read_goal_history"}
    assert store.get(goal.id) == done


async def test_chat_turn_gets_no_goal_tools_while_goals_are_off(monkeypatch, tmp_path):
    from goals import GoalStore

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-goals-off", "Arrange appointments", "profile-1")
    tools = await _goal_tools_for_chat_turn(monkeypatch, store, goal.conversation_id, enabled=lambda: False)
    assert not tools & _GOAL_TOOLS
    assert store.get(goal.id) == goal


async def test_goal_wakeup_is_durable_system_activity_with_model_context(monkeypatch, tmp_path):
    from goals import GoalStore
    from goals._scheduling import GoalWorkSource
    from scheduling import Scheduler

    store = GoalStore(tmp_path / "goals")
    goal = store.create("runner-wakeup", "Plan a household move", "profile-1")

    async def execute(self, **kwargs):
        messages = kwargs["history"].messages
        assert any(message.get("content", "").startswith("[System activity: goal wakeup]") for message in messages)
        return ExecutionResult("success", output="Created a moving checklist")

    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = AgentRuntime(goal_store=store)
    try:
        scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
        scheduler.register(GoalWorkSource(store, runtime, enabled=lambda: True))
        await scheduler.tick()
        handle = runtime.active_for_conversation(goal.conversation_id)
        assert handle is not None
        assert (await handle.wait()).status == "success"
        persisted = load_events_jsonl(goal.conversation_id)
        types = [event["type"] for event in persisted]
        assert "goal" in types and "user_message" not in types
        wake = next(event for event in persisted if event["type"] == "goal" and event["data"]["kind"] == "wakeup")
        assert types.index("agent_started") < persisted.index(wake)
    finally:
        await runtime.close()


async def test_goal_provider_tool_sequence_schedules_then_completes_same_chat(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from agent_core.providers import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolCallFunction
    from goals import GoalStore
    from goals._scheduling import GoalWorkSource
    from scheduling import Scheduler

    store = GoalStore(tmp_path / "goals")
    goal = store.create("provider-goal", "Prepare the household schedule", "profile-1")
    calls = []
    step = 0

    async def chat_stream(**kwargs):
        nonlocal step
        calls.append(kwargs["messages"])
        sequence = [
            ("read_goal", {}),
            ("update_goal", {"plan": [{"id": "appointments", "title": "Confirm appointment time",
                                       "status": "in_progress", "notes": "Asked the clinic for times"}]}),
            ("update_goal", {"summary": "Requested appointment availability"}),
            ("choose_next_action", {"action": "schedule", "at": "2099-01-01T12:00:00+00:00",
                                    "note": "Asked the clinic. Checking for a reply later."}),
            None,
            ("read_goal", {}),
            ("update_goal", {"plan": [{"id": "appointments", "status": "done"}]}),
            ("choose_next_action", {"action": "complete", "note": "The clinic confirmed Tuesday at 3 PM.",
                                    "outcome": "The household schedule includes the confirmed appointment"}),
            None,
        ]
        action = sequence[step]
        step += 1
        if action is None:
            yield ChatResponse(message=ChatMessage(content="Schedule updated."), usage=TokenUsage(completion_tokens=5))
        else:
            name, arguments = action
            yield ChatResponse(message=ChatMessage(tool_calls=[
                ToolCall(id=f"goal-tool-{step}", function=ToolCallFunction(name=name, arguments=arguments)),
            ]), usage=TokenUsage(completion_tokens=5))

    provider = MagicMock()
    provider.chat_stream = chat_stream
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: _profile())
    monkeypatch.setattr(factory_module, "get_provider", lambda _provider: provider)
    runtime = AgentRuntime(goal_store=store)
    scheduler = Scheduler(max_concurrent=2, poll_interval=0.01, shutdown_timeout=0)
    scheduler.register(GoalWorkSource(store, runtime, enabled=lambda: True))
    try:
        await scheduler.tick()
        first = runtime.active_for_conversation(goal.conversation_id)
        assert first is not None
        first_result = await first.wait()
        assert first_result.status == "success"
        # Admission capacity is released when the scheduler's observer finishes.
        await asyncio.gather(*(entry.completion for entry in scheduler.active("goals")))
        scheduled = store.get(goal.id)
        assert scheduled.next.kind == "wake" and scheduled.next.reason == "planned"
        assert scheduled.plan[0].status == "in_progress"
        assert scheduled.summary == "Requested appointment availability"
        assert scheduled.next.at == "2099-01-01T12:00:00+00:00"
        assert scheduled.note == "Asked the clinic. Checking for a reply later."
        assert scheduled.claim is None
        await scheduler.tick(datetime(2099, 1, 1, 12, 0, 1, tzinfo=timezone.utc))
        second = runtime.active_for_conversation(goal.conversation_id)
        assert second is not None and second.run_id != first.run_id
        assert (await second.wait()).status == "success"
        completed = store.get(goal.id)
        assert completed.next.kind == "done"
        assert completed.plan[0].status == "done"
        assert completed.claim is None
        await scheduler.tick(datetime(2100, 1, 1, tzinfo=timezone.utc))
        assert step == 9
        assert len(calls) == 9
        persisted = load_events_jsonl(goal.conversation_id)
        assert len([event for event in persisted if event["type"] == "goal" and event["data"]["kind"] == "wakeup"]) == 2
        assert [event["type"] for event in persisted].count("tool_result") == 7
        assert "user_message" not in [event["type"] for event in persisted]
        assert any("Requested appointment availability" in str(message.get("content", "")) for message in calls[6])
        second_wake = [event for event in persisted if event["type"] == "goal" and event["data"]["kind"] == "wakeup"][1]
        assert second_wake["data"]["step"] == "Confirm appointment time"
        assert any("Plan step: Confirm appointment time" in str(message.get("content", "")) for message in calls[5])
    finally:
        await runtime.close()
