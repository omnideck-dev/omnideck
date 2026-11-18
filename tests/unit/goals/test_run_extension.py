"""The goal run extension: goal tools per run, opening events and the closing divider."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.context import APP_TEXT_PREFIX
from agent_core.context._view import build_llm_view
from agent_core.providers import ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolCallFunction
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime
from agent_runtime import _factory as factory_module
from agent_runtime import _runner as runner_module
from agents._agent_profiles import AgentProfile
from conversations import load_events_jsonl
from goals import EDITED_TEXT, GoalRunExtension, GoalRunTrigger, GoalStep, GoalStore, outcome_divider, wakeup_text
from goals._models import GoalDone, GoalError, GoalWait, GoalWake

from tests.unit.goals.support import choose, claim_wake, completed, create, failed

GOAL_TOOLS = {"read_goal", "read_goal_history", "update_goal", "update_goal_questions", "choose_next_action"}


@pytest.fixture(autouse=True)
def _browser_runtime(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    runtime = MagicMock()

    @asynccontextmanager
    async def execution(**_kwargs):
        yield

    runtime.execution = execution
    runtime.close = AsyncMock()
    monkeypatch.setattr("agent_runtime._runtime.BrowserRuntime", lambda: runtime)
    monkeypatch.setattr(runner_module, "BrowserRuntime", lambda: runtime)
    profile = AgentProfile(id="profile-1", name="Test", provider="ollama", model="test-model",
                           system_prompt="test", skills=[])
    monkeypatch.setattr(factory_module, "get_agent_profile", lambda _pid: profile)
    monkeypatch.setattr(runner_module, "get_agent_profile", lambda _pid: profile)
    monkeypatch.setattr(factory_module, "get_provider", lambda _provider: MagicMock())
    return runtime


@pytest.fixture
def store(tmp_path) -> GoalStore:
    return GoalStore(tmp_path / "goals")


class Script:
    """A provider that answers each model call from a list and records what it was sent."""

    def __init__(self, monkeypatch, *steps):
        self.steps = list(steps)
        self.calls: list[list[dict]] = []
        provider = MagicMock()
        provider.chat_stream = self.chat_stream
        monkeypatch.setattr(factory_module, "get_provider", lambda _provider: provider)

    def add(self, *steps):
        self.steps.extend(steps)

    async def chat_stream(self, **kwargs):
        self.calls.append(kwargs["messages"])
        step = self.steps.pop(0)
        if isinstance(step, str):
            yield ChatResponse(message=ChatMessage(content=step), usage=TokenUsage(completion_tokens=1))
            return
        name, arguments = step
        yield ChatResponse(message=ChatMessage(tool_calls=[ToolCall(
            id=f"call-{len(self.calls)}", function=ToolCallFunction(name=name, arguments=arguments),
        )]), usage=TokenUsage(completion_tokens=1))


def runtime_for(store, enabled=lambda: True) -> AgentRuntime:
    return AgentRuntime(extensions=[GoalRunExtension(store, enabled=enabled)])


async def chat(runtime: AgentRuntime, conversation_id: str, message: str = "How is it going?"):
    handle = await runtime.start(AgentRunRequest(conversation_id, message, None, "profile-1"))
    return await handle.wait()


async def wake(runtime: AgentRuntime, store: GoalStore, goal, claim_id: str = "wake-claim"):
    current = store.get(goal.id)
    claimed = store.claim(goal.id, current.next.id, claim_id)
    assert claimed is not None
    trigger = GoalRunTrigger(goal.id, current.next.id, claim_id, current.next.reason, "")
    handle = await runtime.start(AgentRunRequest(goal.conversation_id, "Continue the goal.", None, "profile-1",
                                                 trigger=trigger))
    return await handle.wait()


def goal_events(conversation_id: str) -> list[dict]:
    return [event for event in load_events_jsonl(conversation_id) if event["type"] == "goal"]


async def tools_for_chat_turn(monkeypatch, store, conversation_id, enabled=lambda: True) -> set[str]:
    seen: list[set[str]] = []

    async def execute(self, **kwargs):
        seen.append({tool.__name__ for tool in kwargs["capabilities"].tools})
        return ExecutionResult("success", output="Here is where things stand.")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = runtime_for(store, enabled)
    try:
        assert (await chat(runtime, conversation_id)).status == "success"
    finally:
        await runtime.close()
    return seen[0]


async def test_goal_tools_and_fresh_state_belong_only_to_owning_root(monkeypatch, store):
    goal = store.create("runner-goal-tools", "Organize household appointments", "profile-1")
    seen = []

    async def execute(self, **kwargs):
        context = kwargs["context"]
        tools = {tool.__name__: tool for tool in kwargs["capabilities"].tools}
        if context.parent_execution_id is not None:
            seen.append(("child", set(tools)))
            return ExecutionResult("success", output="Found available times")
        with context.bind("TEST", kwargs["capabilities"]):
            assert json.loads(await tools["read_goal"]())["objective"] == "Organize household appointments"
            assert await tools["update_goal"](summary="Confirmed clinic opening times") == "Saved."
            assert json.loads(await tools["read_goal"]())["summary"] == "Confirmed clinic opening times"
            await tools["spawn_agent"]("Find available times", "profile-1", "HELPER")
            result = await tools["choose_next_action"](
                action="complete", note="Booked both appointments.", outcome="Appointments arranged",
            )
        assert json.loads(result) == {"action": "complete", "outcome": "Appointments arranged"}
        seen.append(("root", set(tools)))
        return ExecutionResult("success", output="Appointments arranged")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = runtime_for(store)
    try:
        handle = await runtime.start(AgentRunRequest(goal.conversation_id, "hello", None, "profile-1"))
        assert (await handle.wait()).status == "success"
        found = dict(seen)
        assert not GOAL_TOOLS & found["child"]
        assert GOAL_TOOLS <= found["root"]
        saved = store.get(goal.id)
        assert saved.next.kind == "done"
        assert saved.claim is None and saved.last_run_id == handle.run_id
    finally:
        await runtime.close()


async def test_chat_turn_on_paused_goal_gets_all_goal_tools(monkeypatch, store):
    goal = store.create("runner-paused-goal", "Arrange appointments", "profile-1")
    store.pause(goal.id)
    assert GOAL_TOOLS <= await tools_for_chat_turn(monkeypatch, store, goal.conversation_id)
    saved = store.get(goal.id)
    assert saved.paused and saved.next == goal.next and saved.claim is None


async def test_chat_turn_on_error_goal_gets_all_goal_tools(monkeypatch, store):
    goal = failed(store, store.create("runner-error-goal", "Arrange appointments", "profile-1"))
    assert GOAL_TOOLS <= await tools_for_chat_turn(monkeypatch, store, goal.conversation_id)
    assert store.get(goal.id).next == goal.next


async def test_chat_turn_on_done_goal_gets_only_read_tools(monkeypatch, store):
    done = completed(store, store.create("runner-done-goal", "Arrange appointments", "profile-1"))
    tools = await tools_for_chat_turn(monkeypatch, store, done.conversation_id)
    assert tools & GOAL_TOOLS == {"read_goal", "read_goal_history"}
    assert store.get(done.id).next == done.next


async def test_chat_turn_gets_no_goal_tools_while_goals_are_off(monkeypatch, store):
    goal = store.create("runner-goals-off", "Arrange appointments", "profile-1")
    tools = await tools_for_chat_turn(monkeypatch, store, goal.conversation_id, enabled=lambda: False)
    assert not tools & GOAL_TOOLS
    assert store.get(goal.id) == goal


async def test_wake_run_is_stopped_while_goals_are_off(monkeypatch, store):
    goal = store.create("runner-wake-off", "Arrange appointments", "profile-1")
    execute = AsyncMock(return_value=ExecutionResult("success"))
    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = runtime_for(store, enabled=lambda: False)
    try:
        assert (await wake(runtime, store, goal)).status == "stopped"
        execute.assert_not_awaited()
    finally:
        await runtime.close()


@pytest.mark.parametrize("reason,text", [
    ("planned", "A goal run started. Read the goal."),
    ("run_now", "A goal run started. Read the goal.\nThe user asked to run the goal now."),
    ("retry", "A goal run started. Read the goal.\nThe last run failed. The user asked to try again."),
    ("interrupted", "A goal run started. Read the goal.\n"
                    "The last run was interrupted. Check what it already did before repeating actions."),
])
def test_wakeup_text_follows_the_wake_reason(reason, text):
    assert wakeup_text(reason) == text


async def test_wakeup_event_carries_model_text(monkeypatch, store):
    goal = store.create("runner-wakeup", "Plan a household move", "profile-1")
    store.update(goal.id, goal.revision, plan=[GoalStep(id="list", title="Make the moving list", status="in_progress")])
    script = Script(monkeypatch, "Created a moving checklist")
    runtime = runtime_for(store)
    try:
        assert (await wake(runtime, store, goal)).status == "success"
    finally:
        await runtime.close()
    persisted = load_events_jsonl(goal.conversation_id)
    assert "user_message" not in [event["type"] for event in persisted]
    wakeup = next(event for event in persisted if event["type"] == "goal")
    assert wakeup["data"]["kind"] == "wakeup"
    assert wakeup["model_text"] == "A goal run started. Read the goal."
    assert script.calls[0] == [
        script.calls[0][0], {"role": "user", "content": f"{APP_TEXT_PREFIX}\nA goal run started. Read the goal."},
    ]
    assert "Make the moving list" not in str(script.calls[0])
    assert build_llm_view(persisted)[0]["content"].startswith(APP_TEXT_PREFIX)


async def test_edit_with_no_run_going_opens_the_next_run_before_the_typed_message(monkeypatch, store):
    goal = store.create("edit-chat", "Plan the reunion", "profile-1")
    script = Script(monkeypatch, "Started.", "Here is what is left.")
    runtime = runtime_for(store)
    try:
        await chat(runtime, goal.conversation_id, "Start planning")
        current = store.get(goal.id)
        store.update(goal.id, current.revision, plan=[GoalStep(id="dj", title="Book a DJ")])
        assert [event["data"]["kind"] for event in goal_events(goal.conversation_id)] == []
        await chat(runtime, goal.conversation_id, "What's left?")
    finally:
        await runtime.close()
    assert [event["data"]["kind"] for event in goal_events(goal.conversation_id)] == ["edited"]
    assert script.calls[1][-2:] == [
        {"role": "user", "content": f"{APP_TEXT_PREFIX}\n{EDITED_TEXT}"},
        {"role": "user", "content": "What's left?"},
    ]


async def test_two_edits_give_one_event_and_it_is_not_repeated(monkeypatch, store):
    goal = store.create("edit-twice", "Plan the reunion", "profile-1")
    Script(monkeypatch, "Started.", "Noted.", "Still noted.")
    runtime = runtime_for(store)
    try:
        await chat(runtime, goal.conversation_id, "Start planning")
        current = store.update(goal.id, store.get(goal.id).revision, summary="Budget is $500.")
        store.update(goal.id, current.revision, objective="Plan the summer reunion")
        await chat(runtime, goal.conversation_id, "Anything new?")
        await chat(runtime, goal.conversation_id, "And now?")
    finally:
        await runtime.close()
    assert [event["data"]["kind"] for event in goal_events(goal.conversation_id)] == ["edited"]


async def test_run_with_no_user_edits_has_no_edited_event(monkeypatch, store):
    goal = store.create("edit-none", "Plan the reunion", "profile-1")
    Script(monkeypatch, "Started.", "Nothing changed.")
    runtime = runtime_for(store)
    try:
        await chat(runtime, goal.conversation_id, "Start planning")
        await chat(runtime, goal.conversation_id, "Anything new?")
    finally:
        await runtime.close()
    assert goal_events(goal.conversation_id) == []


async def test_new_goal_is_not_an_edit_but_a_later_user_edit_is(monkeypatch, store):
    first = completed(store, store.create("second-goal", "Plan the reunion", "profile-1"))
    Script(monkeypatch, "Planned.", "Second goal underway.", "Read the change.")
    runtime = runtime_for(store)
    try:
        await chat(runtime, first.conversation_id, "Thanks")
        second = store.create("second-goal", "Plan the holiday party", "profile-1")
        await wake(runtime, store, second)
        assert [event["data"]["kind"] for event in goal_events("second-goal")] == ["wakeup", "waiting"]
        store.pause(second.id)
        store.update(second.id, store.get(second.id).revision, plan=[GoalStep(id="venue", title="Pick a venue")])
        await chat(runtime, first.conversation_id, "I added a step")
    finally:
        await runtime.close()
    assert [event["data"]["kind"] for event in goal_events("second-goal")] == ["wakeup", "waiting", "edited"]


async def test_running_agent_write_after_a_user_edit_is_refused(monkeypatch, store):
    goal = store.create("edit-mid-run", "Plan the reunion", "profile-1")
    refused = []

    async def execute(self, **kwargs):
        tools = {tool.__name__: tool for tool in kwargs["capabilities"].tools}
        with kwargs["context"].bind("TEST", kwargs["capabilities"]):
            await tools["read_goal"]()
            store.pause(goal.id)
            store.update(goal.id, store.get(goal.id).revision, summary="The user changed this.")
            refused.append(await tools["update_goal"](summary="From the agent"))
        return ExecutionResult("success")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = runtime_for(store)
    try:
        await chat(runtime, goal.conversation_id, "Keep going")
    finally:
        await runtime.close()
    assert refused[0].startswith("Error:")
    assert store.get(goal.id).summary == "The user changed this."


def test_outcome_divider_for_each_change():
    now = datetime.now(timezone.utc)
    due = GoalWake(at=now.isoformat())
    later = GoalWake(at=(now + timedelta(days=1)).isoformat())
    asking = GoalWait(question_ids=["day"])
    kinds = {
        "scheduled": outcome_divider("g", due, later),
        "unchanged schedule": outcome_divider("g", later, later),
        "continue": outcome_divider("g", due, GoalWake(at=now.isoformat())),
        "waiting": outcome_divider("g", due, asking),
        "wait gained a question": outcome_divider("g", asking, GoalWait(question_ids=["day", "place"])),
        "wait lost a question": outcome_divider("g", GoalWait(question_ids=["day", "place"]), asking),
        "error": outcome_divider("g", due, GoalError(message="Rate limit")),
        "error again": outcome_divider("g", GoalError(message="x"), GoalError(message="y")),
        "completed": outcome_divider("g", due, GoalDone(outcome="Booked")),
    }
    shown = {name: event.payload.data.kind if event else None for name, event in kinds.items()}
    assert shown == {
        "scheduled": "scheduled", "unchanged schedule": None, "continue": None, "waiting": "waiting",
        "wait gained a question": "waiting", "wait lost a question": None, "error": "error",
        "error again": None, "completed": "completed",
    }
    assert kinds["waiting"].payload.data.question_count == 1
    assert kinds["scheduled"].payload.data.resume_at == later.at
    assert kinds["scheduled"].model_text is None


async def test_schedule_then_reply_gives_one_divider_after_the_reply(monkeypatch, store):
    goal = store.create("divider-schedule", "Plan the reunion", "profile-1")
    store.update(goal.id, goal.revision, plan=[GoalStep(id="call", title="Call the parks office", status="in_progress")])
    later = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    Script(monkeypatch, ("read_goal", {}),
           ("choose_next_action", {"action": "continue", "note": "Thinking."}),
           ("choose_next_action", {"action": "schedule", "at": later, "note": "Calling back tomorrow."}),
           "I will call the parks office tomorrow.")
    runtime = runtime_for(store)
    try:
        await wake(runtime, store, goal)
    finally:
        await runtime.close()
    persisted = load_events_jsonl(goal.conversation_id)
    dividers = [event for event in persisted if event["type"] == "goal" and event["data"]["kind"] != "wakeup"]
    assert [event["data"]["kind"] for event in dividers] == ["scheduled"]
    reply = max(index for index, event in enumerate(persisted) if event["type"] == "iteration")
    assert persisted.index(dividers[0]) > reply


async def test_chat_turn_that_changes_nothing_gets_no_divider(monkeypatch, store):
    goal = store.create("divider-none", "Plan the reunion", "profile-1")
    store.update(goal.id, goal.revision, plan=[GoalStep(id="call", title="Call", status="in_progress")])
    later = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    claim_wake(store, goal)
    choose(store, goal, action="schedule", at=later)
    store.finish_run(goal.id, "claim", "run-0", "success")
    Script(monkeypatch, "It is scheduled for tomorrow.")
    runtime = runtime_for(store)
    try:
        await chat(runtime, goal.conversation_id)
    finally:
        await runtime.close()
    assert goal_events(goal.conversation_id) == []


async def test_failed_run_gets_an_error_divider_and_goal_tools_publish_none(monkeypatch, store):
    goal = store.create("divider-error", "Plan the reunion", "profile-1")
    store.update(goal.id, goal.revision, plan=[GoalStep(id="call", title="Call", status="in_progress")])

    async def execute(self, **kwargs):
        tools = {tool.__name__: tool for tool in kwargs["capabilities"].tools}
        with kwargs["context"].bind("TEST", kwargs["capabilities"]):
            await tools["read_goal"]()
            await tools["update_goal"](summary="Tried the parks office.")
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(runner_module.AgentExecutor, "execute", execute)
    runtime = runtime_for(store)
    try:
        assert (await wake(runtime, store, goal)).status == "error"
    finally:
        await runtime.close()
    assert [event["data"]["kind"] for event in goal_events(goal.conversation_id)] == ["wakeup", "error"]
    assert store.get(goal.id).next.kind == "error"
