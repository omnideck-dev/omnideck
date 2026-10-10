"""Model-facing working state; older evidence is available through goal history."""

from ._models import Goal

_RECENT_PROGRESS_LIMIT = 3


def goal_context(goal: Goal) -> dict:
    """Expose actionable state without storage metadata or replaying the journal."""
    recent = goal.progress[-_RECENT_PROGRESS_LIMIT:]
    snapshot = {
        "objective": goal.objective,
        "kind": goal.kind,
        "status": goal.status,
        "revision": goal.revision,
        # Preserve the complete replacement inputs, including dependencies and answers.
        "plan": [step.model_dump(mode="json", exclude_defaults=True) for step in goal.plan],
        "questions": [question.model_dump(mode="json", exclude={"updated_at"}) for question in goal.questions],
        "history_count": goal.history_count,
        "earlier_progress_entries": max(0, goal.progress_count - len(recent)),
    }
    for name in (
        "summary", "known_facts", "blocking_question_ids",
        "next_action", "status_reason", "outcome", "resume_at", "wake_reason",
    ):
        value = getattr(goal, name)
        if value:
            snapshot[name] = value
    if goal.claimed_wake_reason:
        snapshot["current_run_reason"] = goal.claimed_wake_reason
    if recent:
        # Past next_action values are superseded by the current next_action above.
        snapshot["progress"] = [{"created_at": entry.created_at, "summary": entry.summary} for entry in recent]
    return snapshot
