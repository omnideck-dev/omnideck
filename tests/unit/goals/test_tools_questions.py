"""update_goal_questions: changes by ID, question versions and answers."""

import json

import pytest

from goals import GoalAnswerSubmission, GoalStore

from tests.unit.goals.support import bind, call, claim_wake, create, goal_tools, root_context


@pytest.fixture
def owned(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = create(store)
    claim_wake(store, goal)
    return store, goal, root_context(), goal_tools(store, goal)


async def change(context, tools, *changes):
    with bind(context):
        await tools["read_goal"]()
        return await call(tools["update_goal_questions"], changes=list(changes))


async def test_unchanged_question_keeps_version_and_answer_sends(owned):
    store, goal, context, tools = owned
    day = {"id": "day", "question": "Which Saturday works?", "choices": ["June 14", "June 21"]}
    assert await change(context, tools, day) == "Saved."
    seen = store.get(goal.id).questions[0].revision
    # The agent lists the same question again while the user types an answer.
    assert await change(context, tools, day) == "Saved."
    assert store.get(goal.id).questions[0].revision == seen
    accepted = store.save_answers("chat", GoalAnswerSubmission(goal_id=goal.id, answers=[
        {"question_id": "day", "question_revision": seen, "answer": "June 14"},
    ]))
    assert [item.answer for item in accepted] == ["June 14"]


async def test_question_text_change_raises_version(owned):
    store, goal, context, tools = owned
    await change(context, tools, {"id": "day", "question": "Which Saturday works?"})
    await change(context, tools, {"id": "day", "question": "Which Saturday in June works?"})
    assert store.get(goal.id).questions[0].revision == 2


async def test_question_status_change_keeps_text_and_choices(owned):
    store, goal, context, tools = owned
    await change(context, tools, {"id": "day", "question": "Which Saturday works?", "choices": ["June 14", "June 21"]})
    await change(context, tools, {"id": "budget", "question": "What is the budget?"})
    await change(context, tools, {"id": "day", "status": "resolved"})
    resolved = store.question(goal.id, "day")
    assert resolved.status == "resolved"
    assert resolved.question == "Which Saturday works?"
    assert resolved.choices == ["June 14", "June 21"]
    assert [item.id for item in store.get(goal.id).questions] == ["budget"]


async def test_new_question_requires_text(owned):
    store, goal, context, tools = owned
    assert await change(context, tools, {"id": "day", "status": "open"}) == "Error: New question 'day' needs its text."
    assert store.get(goal.id).questions == []


async def test_resolved_question_can_be_reopened_with_its_saved_text(owned):
    store, goal, context, tools = owned
    await change(context, tools, {"id": "day", "question": "Which Saturday works?"})
    await change(context, tools, {"id": "day", "status": "withdrawn"})
    await change(context, tools, {"id": "day", "status": "open"})
    question = store.get(goal.id).questions[0]
    assert question.question == "Which Saturday works?" and question.status == "open"


async def test_listing_a_question_marks_its_answers_read(owned):
    store, goal, context, tools = owned
    await change(context, tools, {"id": "day", "question": "Which Saturday works?"})
    store.save_answers("chat", GoalAnswerSubmission(goal_id=goal.id, answers=[
        {"question_id": "day", "question_revision": 1, "answer": "June 14"},
    ]))
    with bind(context):
        view = json.loads(await tools["read_goal"]())
        assert view["questions"][0]["answers"] == [{"answer": "June 14", "new": True}]
        await call(tools["update_goal_questions"], changes=[{"id": "day"}])
        view = json.loads(await tools["read_goal"]())
        assert view["questions"][0]["answers"] == [{"answer": "June 14"}]
    assert store.get(goal.id).questions[0].revision == 1


async def test_question_change_errors_are_text(owned):
    store, goal, context, tools = owned
    assert await change(context, tools) == "Error: Send at least one question change."
    duplicate = await change(context, tools, {"id": "day", "question": "A?"}, {"id": "day", "question": "B?"})
    assert duplicate == "Error: Question IDs must be unique within an update."
    assert store.get(goal.id).revision == goal.revision
