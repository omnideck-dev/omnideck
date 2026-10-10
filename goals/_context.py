"""Bounded working context, with explicit access to archived question history."""

from ._models import Goal


def goal_context(goal: Goal) -> dict:
    """Keep the active questions and useful facts without replaying their entire history."""
    snapshot = goal.model_dump(mode="json")
    snapshot["progress"] = snapshot["progress"][-20:]
    snapshot["earlier_progress_entries"] = max(0, len(goal.progress) - 20)
    snapshot["questions"] = []
    for question in goal.questions:
        if question.status != "open":
            continue
        current = question.model_dump(mode="json", exclude={"history"})
        # Keep unreviewed answers plus the most recent reviewed answers for follow-ups.
        current["answers"] = current["answers"][max(0, question.reviewed_answer_count - 2):]
        snapshot["questions"].append(current)
    snapshot["archived_question_count"] = sum(question.status != "open" for question in goal.questions)
    return snapshot
