"""Goal tool access, the per-run revision tracker, error text and schemas."""

import asyncio
import json
from dataclasses import replace

import pytest

from agent_core.tools._callable_schema import callable_to_json_schema
from goals import GoalRevisionTracker, GoalStore

from tests.unit.goals.support import (
    bind, call, chat_turn, claim_wake, completed, create, future, goal_tools, root_context, with_plan,
)

ALL_TOOLS = {"read_goal", "read_goal_history", "update_goal", "update_goal_questions", "choose_next_action"}


@pytest.fixture
def owned(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = with_plan(store, create(store))
    claim_wake(store, goal)
    return store, goal, root_context(), goal_tools(store, goal)


async def test_tools_require_the_root_execution_of_the_same_chat(owned):
    store, goal, context, tools = owned
    assert (await tools["read_goal"]()).startswith("Error: Goal tools only work in the chat's own run")
    for invalid in (
        replace(context, execution_id="child", parent_execution_id=context.execution_id),
        replace(context, execution_id="different-root"),
    ):
        with bind(invalid):
            assert (await tools["read_goal"]()).startswith("Error: Goal tools only work")
    with bind(replace(context, conversation_id="another-chat")):
        assert (await tools["read_goal"]()) == "Error: This chat's goal no longer exists."
    with bind(context):
        assert json.loads(await tools["read_goal"]())["objective"] == goal.objective


async def test_writes_need_the_claim_but_reads_do_not(owned):
    store, goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        store.release(goal.id, "claim")
        assert json.loads(await tools["read_goal"]())["objective"] == goal.objective
        result = await tools["update_goal"](summary="Late progress")
        assert result == "Error: This run no longer owns the goal. Stop working on the goal."
    assert store.get(goal.id).summary == ""


async def test_write_before_read_is_refused(owned):
    store, goal, context, tools = owned
    with bind(context):
        result = await tools["update_goal"](summary="Skipped reading")
        assert result == "Error: Read the goal with read_goal before changing it."
        result = await tools["choose_next_action"](action="continue", note="Kept going.")
        assert result == "Error: Read the goal with read_goal before changing it."
    assert store.get(goal.id).revision == goal.revision


async def test_write_after_user_answer_is_refused(owned):
    from goals import GoalAnswerSubmission

    store, goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        await call(tools["update_goal_questions"], changes=[{"id": "day", "question": "Which Saturday?"}])
        store.save_answers("chat", GoalAnswerSubmission(goal_id=goal.id, answers=[
            {"question_id": "day", "question_revision": 1, "answer": "June 14"},
        ]))
        result = await tools["choose_next_action"](action="wait_for_input", note="Waiting.", question_ids=["day"])
        assert result == "Error: The goal changed since you last read it. Call read_goal, then try again."
        assert (await tools["update_goal"](summary="Stale")) == result
        view = json.loads(await tools["read_goal"]())
        assert view["questions"][0]["answers"] == [{"answer": "June 14", "new": True}]
        assert await tools["update_goal"](summary="The reunion is on June 14.") == "Saved."


async def test_parallel_goal_writes_in_one_step_both_pass(owned):
    store, goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        results = await asyncio.gather(
            tools["update_goal"](summary="The pavilion costs $80."),
            call(tools["update_goal"], plan=[{"id": "book", "notes": "Called at 9 AM"}]),
        )
    assert results == ["Saved.", "Saved."]
    saved = store.get(goal.id)
    assert saved.summary == "The pavilion costs $80."
    assert saved.plan[0].notes == "Called at 9 AM"


async def test_own_writes_move_the_tracker_forward(owned):
    store, goal, context, _tools = owned
    tracker = GoalRevisionTracker()
    tools = goal_tools(store, goal, tracker=tracker)
    with bind(context):
        await tools["read_goal"]()
        assert tracker.seen == store.get(goal.id).revision
        await tools["update_goal"](summary="First")
        await tools["update_goal"](summary="Second")
        assert tracker.seen == store.get(goal.id).revision
        await tools["read_goal_history"]()
        assert tracker.seen == store.get(goal.id).revision


async def test_refused_call_returns_error_text(owned):
    store, goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        result = await tools["update_goal"]()
        assert result == "Error: Change the plan, the summary, or both."
        result = await call(tools["update_goal"], plan=[{"id": "missing", "status": "done"}])
        assert result == "Error: New step 'missing' needs a title."
        result = await tools["choose_next_action"](action="wait_for_input", note="Waiting.", question_ids=["nope"])
        assert result.startswith("Error: Wait needs existing open questions.")
        result = await tools["read_goal_history"](before=0)
        assert result == "Error: History cursor must be positive."
    assert store.get(goal.id).revision == goal.revision


async def test_bad_arguments_are_left_to_the_runner(owned):
    from pydantic import ValidationError

    _store, _goal, context, tools = owned
    with bind(context):
        await tools["read_goal"]()
        with pytest.raises(ValidationError):
            await tools["choose_next_action"](action="pause", note="Paused.")


async def test_disabling_goals_revokes_existing_tool_closures(owned):
    store, goal, context, _tools = owned
    enabled = [True]
    tools = goal_tools(store, goal, enabled=lambda: enabled[0])
    with bind(context):
        await tools["read_goal"]()
        enabled[0] = False
        assert await tools["update_goal"](summary="Late progress") == "Error: Goals are turned off."
        assert await tools["read_goal"]() == "Error: Goals are turned off."
    assert store.get(goal.id).summary == ""


async def test_read_goal_hides_the_wake_its_own_run_holds(owned):
    store, goal, context, tools = owned
    with bind(context):
        view = json.loads(await tools["read_goal"]())
        assert "next_action" not in view
        await tools["choose_next_action"](action="continue", note="More to do.")
        assert json.loads(await tools["read_goal"]())["next_action"] == {"action": "continue"}


async def test_read_goal_in_a_chat_turn_shows_the_due_wake(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = create(store)
    chat_turn(store, goal, "turn")
    tools = goal_tools(store, goal, "turn")
    with bind(root_context()):
        assert json.loads(await tools["read_goal"]())["next_action"] == {"action": "continue"}


async def test_every_goal_tool_works_on_a_paused_goal(owned):
    store, goal, context, tools = owned
    store.pause(goal.id)
    chat_turn(store, goal, "turn")
    tools = goal_tools(store, goal, "turn")
    with bind(context):
        assert json.loads(await tools["read_goal"]())["paused"] is True
        assert "entries" in json.loads(await tools["read_goal_history"]())
        assert await tools["update_goal"](summary="Still planning.") == "Saved."
        assert await call(tools["update_goal_questions"], changes=[{"id": "day", "question": "Which Saturday?"}]) == "Saved."
        result = json.loads(await tools["choose_next_action"](action="schedule", note="Check Friday.", at=future(3)))
        assert result["action"] == "schedule"
    saved = store.get(goal.id)
    assert saved.paused is True
    assert saved.next.kind == "wake" and saved.next.id != goal.next.id


async def test_read_tools_work_on_done_goal_without_claim(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = completed(store, create(store))
    tools = goal_tools(store, goal, None, read_only=True)
    assert set(tools) == {"read_goal", "read_goal_history"}
    with bind(root_context()):
        view = json.loads(await tools["read_goal"]())
        assert view["next_action"]["action"] == "complete"
        history = json.loads(await tools["read_goal_history"](query="Completed"))
        assert history["entries"][0]["summary"] == "Completed the goal."


def test_goal_tools_have_documented_schemas_without_identifiers(owned):
    _store, _goal, _context, tools = owned
    assert set(tools) == ALL_TOOLS
    for tool in tools.values():
        schema = callable_to_json_schema(tool)["function"]
        assert schema["description"]
        for name, definition in schema["parameters"]["properties"].items():
            assert name not in {"goal_id", "conversation_id", "execution_id", "claim_id", "expected_revision"}
            assert definition["description"]
    plan = callable_to_json_schema(tools["update_goal"])["function"]["parameters"]["properties"]["plan"]
    assert plan["type"] == "array"
    assert set(plan["items"]["properties"]) == {"id", "title", "status", "notes", "depends_on", "before", "remove"}
    assert plan["items"]["required"] == ["id"]
    choose = callable_to_json_schema(tools["choose_next_action"])["function"]["parameters"]
    assert choose["required"] == ["action", "note"]


@pytest.mark.parametrize("tool_name", ["update_goal", "update_goal_questions", "choose_next_action"])
def test_goal_schemas_survive_all_provider_conversions(owned, tool_name):
    from agent_core.providers._anthropic import _convert_tools as anthropic_tools
    from agent_core.providers._openai import _convert_tools as openai_tools
    from agent_core.providers._openai_responses import _convert_tools as responses_tools
    from agent_core.providers._ollama import _build_ollama_kwargs
    from ollama import Tool

    _store, _goal, _context, tools = owned
    tool = tools[tool_name]
    ollama_tools = _build_ollama_kwargs("model", [], [tool], None, False)["tools"]
    schemas = [
        anthropic_tools([tool])[0]["input_schema"],
        openai_tools([tool])[0]["function"]["parameters"],
        responses_tools([tool])[0]["parameters"],
        Tool.model_validate(ollama_tools[0]).model_dump()["function"]["parameters"],
    ]
    for schema in schemas:
        if tool_name == "choose_next_action":
            assert schema["properties"]["action"]["enum"] == ["continue", "schedule", "wait_for_input", "complete"]
            assert schema["required"] == ["action", "note"]
            assert set(schema["properties"]) == {"action", "note", "at", "question_ids", "outcome"}
        elif tool_name == "update_goal":
            assert schema["properties"]["plan"]["type"] == "array"
            assert "summary" in schema["properties"]
        else:
            assert schema["properties"]["changes"]["type"] == "array"
            assert schema["required"] == ["changes"]


def test_plan_argument_is_validated_as_step_changes_before_invocation(owned):
    from agent_core.tools._helpers import _prepare_tool_arguments
    from goals import GoalStepChange

    _store, _goal, _context, tools = owned
    arguments = _prepare_tool_arguments(tools["update_goal"], {"plan": [{"id": "book", "status": "done"}]})
    assert isinstance(arguments["plan"][0], GoalStepChange)
    with pytest.raises(ValueError, match="Invalid value for parameter 'plan'"):
        _prepare_tool_arguments(tools["update_goal"], {"plan": [{"title": "No stable ID"}]})
    with pytest.raises(ValueError, match="Invalid value for parameter 'plan'"):
        _prepare_tool_arguments(tools["update_goal"], {"plan": [{"id": "book", "known_facts": "x"}]})
