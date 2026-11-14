"""How goal wakeups, state notices and transitions appear in the model's view."""

import pytest

from agent_core.context import GOAL_STATE_PREFIX, GOAL_WAKEUP_PREFIX, SYSTEM_ACTIVITY_PREFIX
from agent_core.context._view import build_llm_view

from tests.unit.agent_core.context._event_builders import CONV, ROOT, _iter, _started, _user


def goal_event(data: dict, evt_id: str) -> dict:
    return {
        "id": evt_id, "type": "goal", "timestamp": "2026-01-01T00:00:02", "conversation_id": CONV,
        "agent_id": ROOT, "depth": 0, "goal_id": "goal_1", "data": data,
    }


def wakeup(step: str = "Book the park pavilion", reason: str = "planned", evt_id: str = "evt_w") -> dict:
    return goal_event({"kind": "wakeup", "wake_id": "wake_1", "reason": reason, "step": step}, evt_id)


def test_shared_prefixes_start_with_the_system_activity_marker():
    assert GOAL_STATE_PREFIX.startswith(SYSTEM_ACTIVITY_PREFIX)
    assert GOAL_WAKEUP_PREFIX.startswith(SYSTEM_ACTIVITY_PREFIX)


def test_wakeup_opens_the_view_and_names_the_plan_step():
    messages = build_llm_view([_started(ROOT, "Agent"), wakeup()])
    assert messages == [{"role": "user", "content": (
        f"{GOAL_WAKEUP_PREFIX}\nA goal run started.\nPlan step: Book the park pavilion\n"
        "Read the goal and the step's notes before acting."
    )}]


def test_wakeup_without_an_open_step_asks_for_a_plan_update():
    content = build_llm_view([_started(ROOT, "Agent"), wakeup(step="")])[0]["content"]
    assert "Plan step" not in content
    assert "No plan step is open. Read the goal and update the plan." in content


@pytest.mark.parametrize("reason,text", [
    ("run_now", "The user asked to run the goal now."),
    ("retry", "The last run failed. The user asked to try again."),
    ("interrupted", "The last run was interrupted. Check saved progress and outside state before repeating actions."),
])
def test_wakeup_says_why_the_run_started(reason, text):
    content = build_llm_view([_started(ROOT, "Agent"), wakeup(reason=reason)])[0]["content"]
    assert text in content


def test_later_wakeup_follows_earlier_turns():
    events = [
        _started(ROOT, "Agent"), _user(ROOT, "Plan the reunion"), _iter(ROOT, 0, content="Started a plan."),
        wakeup(evt_id="evt_w2"),
    ]
    messages = build_llm_view(events)
    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"].startswith(GOAL_WAKEUP_PREFIX)


@pytest.mark.parametrize("reason,text", [
    ("run_started", "This chat has a goal. Read the goal before goal work."),
    ("state_changed", "The goal changed since you last read it. Read it again before more goal work."),
    ("compacted", "Earlier messages were compacted. Read the goal again before more goal work."),
])
def test_state_notice_names_no_tool_or_revision(reason, text):
    events = [
        _started(ROOT, "Agent"), _user(ROOT, "How is it going?"),
        goal_event({"kind": "state_notice", "revision": 7, "reason": reason}, "evt_n"),
    ]
    notice = build_llm_view(events)[-1]
    assert notice == {"role": "user", "content": f"{GOAL_STATE_PREFIX}\n{text}"}
    assert "read_goal" not in notice["content"] and "7" not in notice["content"]


def test_transitions_are_not_shown_to_the_model():
    events = [
        _started(ROOT, "Agent"), _user(ROOT, "How is it going?"),
        goal_event({"kind": "paused", "objective": "", "resume_at": None, "question_count": 0}, "evt_t"),
    ]
    assert build_llm_view(events) == [{"role": "user", "content": "How is it going?"}]
