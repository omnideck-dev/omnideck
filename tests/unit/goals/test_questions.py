"""Question lifecycle, answer races, and durable question history."""

import pytest

from goals import GoalAnswerSubmission, GoalConflictError, GoalQuestionChange, GoalStateError, GoalStore
from goals._context import goal_context

from tests.unit.goals.support import ask, choose, claim_wake


@pytest.fixture
def owner(tmp_path):
    store = GoalStore(tmp_path)
    goal = store.create("chat", "Find a dentist", "assistant")
    claim_wake(store, goal)
    return store, goal


def change(store, goal, *changes):
    current = store.get(goal.id)
    return store.update_questions(goal.id, list(changes), current.revision, claim_id="claim")


def submit(store, goal, answers, conversation="chat"):
    return store.save_answers(conversation, GoalAnswerSubmission(goal_id=goal.id, answers=answers))


def insurance(**fields):
    return GoalQuestionChange(id="insurance", **({"question": "Which insurance plan?"} | fields))


def test_asking_does_not_wait_and_partial_answers_need_agent_review(owner):
    store, goal = owner
    asked = change(store, goal, insurance(), GoalQuestionChange(id="travel", question="How far can you travel?"))
    assert asked.next == goal.next
    choose(store, goal, action="wait_for_input", question_ids=["insurance", "travel"])
    assert not store.due()
    accepted = submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna Dental PPO"}])
    assert accepted[0].answer == "Aetna Dental PPO"
    assert accepted[0].question == "Which insurance plan?"
    latest = store.get(goal.id)
    assert latest.questions[0].status == "open"
    assert latest.next.question_ids == ["insurance", "travel"]
    with pytest.raises(GoalConflictError, match="New answers"):
        choose(store, goal, action="wait_for_input", question_ids=["insurance"])
    change(store, goal, GoalQuestionChange(id="insurance", status="resolved"))
    latest = store.get(goal.id)
    assert latest.next.question_ids == ["travel"]
    assert [item["id"] for item in goal_context(latest)["questions"]] == ["travel"]


def test_revised_question_rejects_stale_and_cross_chat_answers_atomically(owner):
    store, goal = owner
    change(store, goal, insurance(), GoalQuestionChange(id="travel", question="How far?"))
    revised = change(store, goal, insurance(question="Which dental insurer and plan?"))
    assert revised.questions[0].revision == 2
    with pytest.raises(GoalConflictError, match="question changed"):
        submit(store, goal, [
            {"question_id": "travel", "question_revision": 1, "answer": "10 miles"},
            {"question_id": "insurance", "question_revision": 1, "answer": "Aetna"},
        ])
    assert all(not item.answers for item in store.get(goal.id).questions)
    with pytest.raises(GoalConflictError, match="another conversation"):
        submit(store, goal, [{"question_id": "insurance", "question_revision": 2, "answer": "Aetna"}], "other")
    assert any(entry["data"].get("question") == "Which insurance plan?" for entry in store.read_history(goal.id)["entries"])


def test_uncertain_answer_can_be_reviewed_and_withdrawn_question_keeps_history(owner):
    store, goal = owner
    change(store, goal, insurance())
    submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Not sure"}])
    goal = change(store, goal, insurance(question="Can you check your benefits card?"))
    assert goal.questions[0].reviewed_answer_count == 1
    choose(store, goal, action="wait_for_input", question_ids=["insurance"])
    goal = change(store, goal, GoalQuestionChange(id="insurance", status="withdrawn"))
    restored = GoalStore(store._base).get(goal.id)
    assert restored.questions == []
    assert restored.next.question_ids == []
    assert store.question(goal.id, "insurance").status == "withdrawn"
    assert any(entry["data"].get("answer") == "Not sure" for entry in store.read_history(goal.id)["entries"])
    with pytest.raises(GoalStateError):
        choose(store, goal, action="wait_for_input", question_ids=["insurance"])


def test_answers_keep_pause_and_cannot_change_an_ended_goal(owner):
    store, goal = owner
    change(store, goal, insurance())
    store.pause(goal.id)
    submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}])
    assert store.get(goal.id).paused and not store.due()
    store.cancel(goal.id)
    with pytest.raises(GoalStateError):
        submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Cigna"}])
    assert len(store.question(goal.id, "insurance").answers) == 1


def test_accepted_answer_keeps_question_wording_after_question_is_revised(owner):
    store, goal = owner
    change(store, goal, insurance())
    accepted = submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}])
    change(store, goal, insurance(question="Which specific dental plan?"))
    assert accepted[0].question == "Which insurance plan?"
    assert accepted[0].question_revision == 1
    assert store.get(goal.id).questions[0].question == "Which specific dental plan?"


def test_save_answers_ignores_duplicate_answer(owner):
    store, goal = owner
    change(store, goal, insurance())
    answer = {"question_id": "insurance", "question_revision": 1, "answer": "Aetna Dental PPO"}
    assert len(submit(store, goal, [answer])) == 1
    revision = store.get(goal.id).revision
    assert submit(store, goal, [answer]) == []
    saved = store.get(goal.id)
    assert len(saved.questions[0].answers) == 1
    assert saved.revision == revision
    assert len([entry for entry in store.read_history(goal.id)["entries"] if entry["kind"] == "answer"]) == 1


def test_duplicate_answer_beside_a_new_one_saves_only_the_new_one(owner):
    store, goal = owner
    change(store, goal, insurance(), GoalQuestionChange(id="travel", question="How far?"))
    first = {"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}
    submit(store, goal, [first])
    accepted = submit(store, goal, [first, {"question_id": "travel", "question_revision": 1, "answer": "10 miles"}])
    assert [item.question_id for item in accepted] == ["travel"]
    saved = {item.id: item for item in store.get(goal.id).questions}
    assert len(saved["insurance"].answers) == 1 and len(saved["travel"].answers) == 1


def test_a_different_answer_to_the_same_question_is_saved(owner):
    store, goal = owner
    change(store, goal, insurance())
    submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Aetna"}])
    accepted = submit(store, goal, [{"question_id": "insurance", "question_revision": 1, "answer": "Actually Cigna"}])
    assert [item.answer for item in accepted] == ["Actually Cigna"]
    assert len(store.get(goal.id).questions[0].answers) == 2


def test_one_answer_per_question_per_submission(owner):
    store, goal = owner
    ask(store, goal, question_id="insurance", text="Which insurance plan?")
    with pytest.raises(ValueError, match="one answer per question"):
        submit(store, goal, [
            {"question_id": "insurance", "question_revision": 1, "answer": "Aetna"},
            {"question_id": "insurance", "question_revision": 1, "answer": "Cigna"},
        ])
