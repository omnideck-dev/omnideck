"""Question lifecycle, answer races, bounded context, and durable history."""

import json

import pytest

from agent_core.agent_capabilities import AgentCapabilities
from agent_core.context import ConversationHistory
from agent_core.control import ExecutionControl
from agent_core.turn import ExecutionContext
from goals import GoalAnswerSubmission, GoalConflictError, GoalQuestionChange, GoalStateError, GoalStore, make_goal_tools
from goals._context import goal_context


@pytest.fixture
def owner(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create("chat", "Find a dentist", "assistant")
    goal = store.claim(goal.id, goal.wake_id, "claim")
    return store, goal


def question(id="insurance", text="Which insurance plan?", status="open"):
    return GoalQuestionChange(id=id, question=text, status=status)


def submit(store, goal, answers):
    return store.submit_answers("chat", GoalAnswerSubmission(goal_id=goal.id, answers=answers))


def test_asking_does_not_wait_and_partial_answers_require_agent_resolution(owner):
    store, goal = owner
    goal = store.update_questions(goal.id, [question(), question("travel", "How far can you travel?")], "", goal.revision, claim_id="claim")
    assert goal.status == "active" and goal.wake_id is None
    waiting = store.wait_for_input(goal.id, ["insurance", "travel"], claim_id="claim")
    assert waiting.status == "needs_input" and not store.due()
    text = submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna Dental PPO"}])
    assert "[insurance] Which insurance plan?\nAetna Dental PPO" in text
    latest = store.get(goal.id)
    assert latest.questions[0].status == "open"
    with pytest.raises(GoalConflictError, match="New answers"):
        store.wait_for_input(goal.id, ["insurance"], claim_id="claim")
    with pytest.raises(GoalConflictError, match="Goal changed"):
        store.update_questions(goal.id, [question(status="resolved")], "", waiting.revision, claim_id="claim")
    latest = store.update_questions(goal.id, [question(status="resolved")], "Insurance: Aetna Dental PPO.", latest.revision, claim_id="claim")
    latest = store.wait_for_input(goal.id, ["travel"], claim_id="claim")
    assert latest.blocking_question_ids == ["travel"]
    assert [q["id"] for q in goal_context(latest)["questions"]] == ["travel"]
    assert goal_context(latest)["known_facts"] == "Insurance: Aetna Dental PPO."


def test_revisions_preserve_old_wording_and_reject_stale_or_cross_chat_answers_atomically(owner):
    store, goal = owner
    goal = store.update_questions(goal.id, [question(), question("travel", "How far?")], "", goal.revision, claim_id="claim")
    goal = store.update_questions(goal.id, [question(text="Which dental insurer and plan?")], "", goal.revision, claim_id="claim")
    with pytest.raises(GoalConflictError, match="question changed"):
        submit(store, goal, [
            {"question_id": "travel", "question_revision": 1, "answer": "10 miles"},
            {"question_id": "insurance", "question_revision": 1, "answer": "Aetna"},
        ])
    assert all(not q.answers for q in store.get(goal.id).questions)
    with pytest.raises(GoalConflictError, match="another conversation"):
        store.submit_answers("other", GoalAnswerSubmission(goal_id=goal.id, answers=[
            {"question_id": "insurance", "question_revision": 2, "answer": "Aetna"},
        ]))
    assert any(entry["data"].get("question") == "Which insurance plan?" for entry in store.read_history(goal.id)["entries"])


def test_uncertain_answers_can_be_reviewed_and_question_withdrawal_keeps_history(owner):
    store, goal = owner
    goal = store.update_questions(goal.id, [question()], "", goal.revision, claim_id="claim")
    submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Not sure"}])
    goal = store.get(goal.id)
    goal = store.update_questions(goal.id, [question(text="Can you check your benefits card?")], "", goal.revision, claim_id="claim")
    assert goal.questions[0].reviewed_answer_count == 1
    store.wait_for_input(goal.id, ["insurance"], claim_id="claim")
    goal = store.get(goal.id)
    goal = store.update_questions(goal.id, [question(status="withdrawn")], "Find cash-pay options.", goal.revision, claim_id="claim")
    restored = GoalStore(store._base).get(goal.id)
    assert restored.questions == []
    assert store.question(goal.id, "insurance").status == "withdrawn"
    assert any(entry["data"].get("answer") == "Not sure" for entry in store.read_history(goal.id)["entries"])
    assert restored.blocking_question_ids == []
    with pytest.raises(GoalStateError):
        store.wait_for_input(goal.id, ["insurance"], claim_id="claim")


def test_answers_preserve_explicit_pause_and_cannot_change_terminal_goal(owner):
    store, goal = owner
    goal = store.update_questions(goal.id, [question()], "", goal.revision, claim_id="claim")
    store.pause(goal.id)
    submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}])
    assert store.get(goal.id).status == "paused" and not store.due()
    store.cancel(goal.id)
    with pytest.raises(GoalStateError):
        submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Cigna"}])


async def test_tool_results_and_model_context_exclude_archives_until_explicit_read(owner):
    store, goal = owner
    goal = store.update_questions(goal.id, [question(str(i), f"Question {i}", "resolved") for i in range(45)], "Current facts only", goal.revision, claim_id="claim")
    context = ExecutionContext(execution_id="root.test", conversation_id="chat", run_id="run", event_sink=ConversationHistory(conversation_id="chat"), control=ExecutionControl())
    tools = {fn.__name__: fn for fn in make_goal_tools(store, goal.id, context.execution_id, claim_id="claim")}
    with context.bind("Test", AgentCapabilities([])):
        current = json.loads(await tools["read_goal"]())
        assert current["questions"] == [] and current["history_count"] >= 45
        assert "Question 0" not in json.dumps(current)
        history = json.loads(await tools["read_goal_history"](query="Question"))
        assert len(history["entries"]) == 20 and history["next_before"]
        assert history["entries"][0]["data"]["id"] == "44"
        progress = json.loads(await tools["record_goal_progress"]("Checked evidence", "Continue"))
        assert progress["questions"] == []
