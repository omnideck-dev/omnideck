"""The agent's view of a goal: the whole goal in the words of its tools."""

import json
from datetime import datetime, timedelta, timezone

from goals import GoalStep
from goals._context import goal_context
from goals._models import (
    Goal, GoalAnswer, GoalCancelled, GoalClaim, GoalDone, GoalError, GoalQuestion, GoalWait, GoalWake, local_time,
)


def goal(**fields) -> Goal:
    return Goal(conversation_id="chat", profile_id="assistant", objective="Book the park pavilion for the reunion",
                **fields)


def in_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_wake_run_view_hides_held_next_action():
    wake = GoalWake(at=in_days(-1))
    view = goal_context(goal(next=wake, claim=GoalClaim(id="claim", wake_id=wake.id)), held_wake_id=wake.id)
    assert "next_action" not in view


def test_wake_run_view_shows_a_new_choice_after_the_held_wake():
    held = GoalWake(at=in_days(-1))
    chosen = GoalWake(at=in_days(2))
    view = goal_context(goal(next=chosen), held_wake_id=held.id)
    assert view["next_action"] == {"action": "schedule", "at": local_time(chosen.at)}


def test_chat_turn_view_shows_next_action():
    due = goal(next=GoalWake(at=in_days(-1)), claim=GoalClaim(id="turn"))
    assert goal_context(due)["next_action"] == {"action": "continue"}
    later = GoalWake(at=in_days(3))
    assert goal_context(goal(next=later))["next_action"] == {"action": "schedule", "at": local_time(later.at)}
    assert goal_context(goal(next=GoalWait(question_ids=["day"])))["next_action"] == {
        "action": "wait_for_input", "question_ids": ["day"],
    }
    assert goal_context(goal(next=GoalDone(outcome="Booked June 14.")))["next_action"] == {
        "action": "complete", "outcome": "Booked June 14.",
    }


def test_view_has_no_next_action_when_the_agent_did_not_choose():
    view = goal_context(goal(next=GoalWait()))
    assert "next_action" not in view


def test_view_shows_error_pause_and_cancel():
    errored = goal_context(goal(next=GoalError(message="Rate limit reached (429)."), paused=True))
    assert errored["error"] == "Rate limit reached (429)."
    assert errored["paused"] is True
    assert "next_action" not in errored
    cancelled = goal_context(goal(next=GoalCancelled()))
    assert cancelled["cancelled"] is True
    assert "next_action" not in cancelled
    plain = goal_context(goal())
    assert not {"error", "paused", "cancelled"} & plain.keys()


def test_view_has_now_and_note_and_no_storage_words():
    item = goal(
        summary="The pavilion costs $80 a day.", note="Called the parks office.",
        claim=GoalClaim(id="private-claim", wake_id="private-wake"), history_count=1100, last_run_id="run-secret",
    )
    view = goal_context(item)
    assert view["note"] == "Called the parks office."
    assert view["summary"] == "The pavilion costs $80 a day."
    now = datetime.fromisoformat(view["now"].split(" ")[0])
    assert now.utcoffset() is not None
    assert abs(now - datetime.now(timezone.utc)) < timedelta(minutes=2)
    serialized = json.dumps(view)
    for word in ("revision", "claim", "wake", "status_reason", "history_count", "private-claim", "run-secret",
                 "conversation_id", "profile_id", "known_facts"):
        assert word not in serialized
    assert '"status"' not in json.dumps({key: value for key, value in view.items() if key not in {"plan", "questions"}})


def test_view_leaves_out_an_empty_summary_and_note():
    view = goal_context(goal())
    assert "summary" not in view and "note" not in view
    assert view["plan"] == [] and view["questions"] == []


def test_view_keeps_full_plan_and_marks_new_answers():
    item = goal(
        plan=[GoalStep(id="check", title="Check the pavilion price", status="done", notes="Confirmed $80"),
              GoalStep(id="book", title="Book the pavilion", depends_on=["check"])],
        questions=[GoalQuestion(
            id="day", question="Which Saturday?", status="open", revision=2, reviewed_answer_count=1,
            choices=["June 14", "June 21"], answers=[
                GoalAnswer(question_id="day", question_revision=1, answer="Afternoons only"),
                *[GoalAnswer(question_id="day", question_revision=2, answer=f"Correction {i}") for i in range(3)],
            ],
        )],
    )
    view = goal_context(item)
    assert [GoalStep.model_validate(step) for step in view["plan"]] == item.plan
    assert view["plan"][1] == {"id": "book", "title": "Book the pavilion", "depends_on": ["check"]}
    question = view["questions"][0]
    assert question["choices"] == ["June 14", "June 21"]
    assert question["answers"][0] == {"answer": "Afternoons only"}
    assert question["answers"][1:] == [{"answer": f"Correction {i}", "new": True} for i in range(3)]
    assert "revision" not in question and "reviewed_answer_count" not in question
