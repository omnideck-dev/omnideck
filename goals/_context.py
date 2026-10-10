"""Bounded working context, with explicit access to archived question history."""

from ._models import Goal


def goal_context(goal: Goal) -> dict:
    """Keep the active questions and useful facts without replaying their entire history."""
    snapshot = goal.model_dump(mode="json")
    snapshot["earlier_progress_entries"] = max(0, goal.progress_count - len(goal.progress))
    return snapshot
