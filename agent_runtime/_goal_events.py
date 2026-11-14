"""Lifecycle events emitted when a goal change is committed."""

from datetime import datetime

from agent_core.events import AgentEvent, GoalEventPayload, GoalTransitionData

from goals._models import GoalHistoryEntry

_ENDED_TRANSITIONS = {"error": "error", "done": "completed", "cancelled": "cancelled"}


def _state_transition(before: dict, after: dict, created_at: str) -> tuple[str, dict] | None:
    previous, following = before["next"], after["next"]
    # Pause never changes the kind of next step; it may mark a held wake interrupted.
    if after["paused"] and not before["paused"]:
        return "paused", {}
    if following != previous:
        kind = following["kind"]
        if kind in _ENDED_TRANSITIONS:
            return _ENDED_TRANSITIONS[kind], {}
        if kind == "wait":
            if previous["kind"] in {"done", "cancelled"}:
                return "reopened", {}
            # A wait that gains new questions is announced; one that only loses answered ones is not.
            if previous["kind"] != "wait" or set(following["question_ids"]) - set(previous["question_ids"]):
                return "waiting", {"question_count": len(following["question_ids"])}
            return None
        # A wake due now gets its own run divider when it starts; only a later run is announced here.
        if following["reason"] == "planned" and datetime.fromisoformat(following["at"]) > datetime.fromisoformat(created_at):
            return "scheduled", {"resume_at": following["at"]}
        return None
    if after["paused"] != before["paused"]:
        return ("paused" if after["paused"] else "resumed"), {}
    return None


def goal_transition_event(goal_id: str, entry: GoalHistoryEntry) -> AgentEvent | None:
    """Reuse a journal entry's identity and time for its conversation divider."""
    data = entry['data']
    transition = None
    fields: dict = {}
    objective = ''
    if entry['kind'] == 'goal' and 'before' not in data:
        transition = 'started'
        objective = data['objective']
    elif entry['kind'] == 'state':
        found = _state_transition(data['before'], data['after'], entry['created_at'])
        if found is not None:
            transition, fields = found
    if transition is None:
        return None
    return AgentEvent(
        id=f"goal_{goal_id}_history_{entry['id']}",
        timestamp=datetime.fromisoformat(entry['created_at']),
        payload=GoalEventPayload(
            type='goal', goal_id=goal_id,
            data=GoalTransitionData(
                kind=transition, objective=objective, resume_at=fields.get('resume_at'),
                question_count=fields.get('question_count', 0),
            ),
        ),
    )
