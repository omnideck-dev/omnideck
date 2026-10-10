"""Root-owned goal tools and their model-facing contracts."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.context import ConversationHistory
from agent_core.control import ExecutionControl
from agent_core.tools._callable_schema import callable_to_json_schema
from agent_core.turn import ExecutionContext
from goals import GoalConflictError, GoalStateError, GoalQuestionChange, GoalStep, GoalStore, make_goal_tools


@pytest.fixture
def owned_goal(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = store.create("chat", "Keep the household calendar up to date", "assistant", kind="ongoing")
    store.claim(goal.id, goal.wake_id, "claim")
    context = ExecutionContext(
        execution_id="root.agent.owner", conversation_id="chat", run_id="runtime-run",
        event_sink=ConversationHistory(conversation_id="chat"), control=ExecutionControl(),
    )
    tools = {tool.__name__: tool for tool in make_goal_tools(store, goal.id, context.execution_id, claim_id="claim")}
    return store, goal, context, tools


async def test_tools_require_root_identity_conversation_and_current_claim(owned_goal):
    store, goal, context, tools = owned_goal
    read = tools["read_goal"]
    with pytest.raises(GoalConflictError):
        await read()
    for invalid in (
        replace(context, execution_id="child", parent_execution_id=context.execution_id),
        replace(context, conversation_id="another-chat"),
        replace(context, execution_id="different-root"),
    ):
        with invalid.bind("Agent", AgentCapabilities([])), pytest.raises(GoalConflictError):
            await read()
    with context.bind("Agent", AgentCapabilities([])):
        assert json.loads(await read())["objective"] == goal.objective
        store.release(goal.id, "claim")
        with pytest.raises(GoalConflictError):
            await read()


async def test_plan_and_progress_use_revision_and_never_implicitly_schedule(owned_goal):
    store, goal, context, tools = owned_goal
    with context.bind("Agent", AgentCapabilities([])):
        snapshot = json.loads(await tools["read_goal"]())
        updated = json.loads(await tools["update_goal_plan"](
            [GoalStep(id="calendar", title="Check the school calendar")], "Check upcoming school dates", snapshot["revision"],
        ))
        with pytest.raises(GoalConflictError):
            await tools["update_goal_plan"]([], "Plan changed", snapshot["revision"])
        progress = json.loads(await tools["record_goal_progress"]("Found the school calendar", "Draft next week"))
    assert updated["revision"] == snapshot["revision"] + 1
    assert progress["revision"] > updated["revision"]
    assert "plan" not in updated and "progress" not in progress
    assert store.get(goal.id).plan[0].id == "calendar"
    assert store.get(goal.id).progress[0].summary == "Found the school calendar"
    assert store.get(goal.id).wake_id is None


async def test_agent_explicitly_selects_each_disposition(owned_goal):
    store, goal, context, tools = owned_goal
    with context.bind("Agent", AgentCapabilities([])):
        continued = json.loads(await tools["continue_goal"]("More work remains", "Draft next week"))
        assert continued["status"] == "active" and continued["resume_at"]
        continued_wake = store.get(goal.id).wake_id
        scheduled = json.loads(await tools["schedule_goal_resume"](
            (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "Check for replies", "Review replies",
        ))
        assert scheduled["status"] == "scheduled" and scheduled["resume_at"]
        assert store.get(goal.id).wake_id != continued_wake
        await tools["update_goal_questions"]([GoalQuestionChange(id="calendar", question="Which school calendar is current?", status="open")], "", scheduled["revision"])
        waiting = json.loads(await tools["wait_for_goal_input"](["calendar"]))
        assert waiting["status"] == "needs_input" and waiting["blocking_question_ids"] == ["calendar"]
        assert store.get(goal.id).wake_id is None
        completed = json.loads(await tools["complete_goal"]("The calendar is complete and shared"))
        assert completed["status"] == "completed" and completed["outcome"] == "The calendar is complete and shared"
        assert store.get(goal.id).claimed_run_id == "claim"
        with pytest.raises(GoalStateError):
            await tools["continue_goal"]("Keep going", "Another task")
    assert store.get(goal.id).wake_id is None


async def test_disabling_goals_immediately_revokes_existing_tool_closures(owned_goal):
    store, goal, context, _tools = owned_goal
    enabled = [True]
    tools = {tool.__name__: tool for tool in make_goal_tools(
        store, goal.id, context.execution_id, claim_id="claim", enabled=lambda: enabled[0],
    )}
    with context.bind("Agent", AgentCapabilities([])):
        await tools["read_goal"]()
        enabled[0] = False
        with pytest.raises(GoalStateError, match="disabled"):
            await tools["record_goal_progress"]("Late progress", "Continue")
        with pytest.raises(GoalStateError, match="disabled"):
            await tools["read_goal"]()
    assert store.get(goal.id).progress == []


def test_goal_tools_have_documented_schemas_without_cross_goal_identifiers(owned_goal):
    _store, goal, _context, tools = owned_goal
    for tool in tools.values():
        schema = callable_to_json_schema(tool)["function"]
        assert schema["description"]
        for name, definition in schema["parameters"]["properties"].items():
            assert name not in {"goal_id", "conversation_id", "execution_id", "claim_id"}
            assert definition["description"]
    plan_schema = callable_to_json_schema(tools["update_goal_plan"])["function"]["parameters"]["properties"]
    assert plan_schema["plan"]["type"] == "array"
    assert plan_schema["plan"]["items"]["type"] == "object"
    assert set(plan_schema["plan"]["items"]["properties"]) == {"id", "title", "status", "notes", "depends_on"}
    assert plan_schema["plan"]["items"]["required"] == ["id", "title"]
    for field in plan_schema["plan"]["items"]["properties"].values():
        assert field["description"]


def test_plan_schema_survives_all_provider_conversions(owned_goal):
    from agent_core.providers._anthropic import _convert_tools as anthropic_tools
    from agent_core.providers._openai import _convert_tools as openai_tools
    from agent_core.providers._openai_responses import _convert_tools as responses_tools
    from agent_core.providers._ollama import _build_ollama_kwargs
    from ollama import Tool

    _store, _goal, _context, tools = owned_goal
    plan_tool = tools["update_goal_plan"]
    ollama_tools = _build_ollama_kwargs("model", [], [plan_tool], None, False)["tools"]
    ollama_schema = Tool.model_validate(ollama_tools[0]).model_dump()["function"]["parameters"]
    schemas = [
        anthropic_tools([plan_tool])[0]["input_schema"],
        openai_tools([plan_tool])[0]["function"]["parameters"],
        responses_tools([plan_tool])[0]["parameters"],
        ollama_schema,
    ]
    for schema in schemas:
        plan = schema["properties"]["plan"]
        assert plan["type"] == "array"
        assert plan["items"]["required"] == ["id", "title"]
        assert plan["items"]["properties"]["status"]["enum"] == [
            "pending", "in_progress", "done", "blocked", "skipped",
        ]


async def test_plan_tool_validates_json_as_steps_before_invocation(owned_goal):
    from agent_core.tools._helpers import _prepare_tool_arguments

    store, goal, context, tools = owned_goal
    revision = store.get(goal.id).revision
    tool = tools["update_goal_plan"]
    arguments = _prepare_tool_arguments(tool, {
        "plan": [{"id": "review", "title": "Review calendar", "status": "pending"}],
        "expected_revision": revision, "reason": "Check upcoming school dates",
    })
    assert isinstance(arguments["plan"][0], GoalStep)
    with context.bind("Agent", AgentCapabilities([])):
        await tool(**arguments)
    assert store.get(goal.id).plan[0].id == "review"
    with pytest.raises(ValueError, match="Invalid value for parameter 'plan'"):
        _prepare_tool_arguments(tool, {"plan": [{"title": "No stable ID"}], "expected_revision": revision})
