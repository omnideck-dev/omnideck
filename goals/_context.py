"""The agent's view of a goal, in the words of its tools."""

from datetime import datetime, timezone

from ._models import Goal, GoalQuestion, local_time


def _now() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.astimezone().isoformat(timespec='minutes')} ({local_time(now)})"


def _question(question: GoalQuestion) -> dict:
    view: dict = {"id": question.id, "question": question.question, "status": question.status}
    if question.choices:
        view["choices"] = question.choices
    answers = [
        {"answer": answer.answer, **({"new": True} if index >= question.reviewed_answer_count else {})}
        for index, answer in enumerate(question.answers)
    ]
    if answers:
        view["answers"] = answers
    return view


def next_action_view(goal: Goal) -> dict | None:
    """What happens next, in choose_next_action's words."""
    following = goal.next
    if following.kind == "wake":
        if datetime.fromisoformat(following.at) <= datetime.now(timezone.utc):
            return {"action": "continue"}
        return {"action": "schedule", "at": local_time(following.at)}
    if following.kind == "wait":
        return {"action": "wait_for_input", "question_ids": following.question_ids} if following.question_ids else None
    if following.kind == "done":
        return {"action": "complete", "outcome": following.outcome}
    return None


def goal_context(goal: Goal, *, held_wake_id: str | None = None) -> dict:
    """The whole goal without storage words.

    ``held_wake_id`` is the wake the reader's own run took. While it is still
    the next action, the next action is left out: the run has not chosen yet.
    """
    view: dict = {
        "objective": goal.objective,
        "now": _now(),
        "plan": [step.model_dump(mode="json", exclude_defaults=True) for step in goal.plan],
        "questions": [_question(question) for question in goal.questions],
    }
    if goal.summary:
        view["summary"] = goal.summary
    if goal.note:
        view["note"] = goal.note
    if goal.paused:
        view["paused"] = True
    if goal.next.kind == "error":
        view["error"] = goal.next.message
    if goal.next.kind == "cancelled":
        view["cancelled"] = True
    holding = held_wake_id is not None and goal.next.kind == "wake" and goal.next.id == held_wake_id
    following = None if holding else next_action_view(goal)
    if following is not None:
        view["next_action"] = following
    return view
