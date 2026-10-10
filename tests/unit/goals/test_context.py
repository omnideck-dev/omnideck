"""Default model context stays small without dropping actionable goal state."""

import json

from agent_core.context import ConversationHistory
from agent_runtime._goals import GoalContextHook
from goals import GoalStep, GoalStore
from goals._context import goal_context
from goals._models import Goal, GoalAnswer, GoalProgress, GoalQuestion


def test_context_limits_progress_and_excludes_execution_metadata():
    goal = Goal(
        conversation_id="chat", profile_id="assistant", objective="Grow the newsletter to 100 subscribers. Ask before spending.",
        summary="Library referrals work; avoid paid ads.", known_facts="Budget: $100/month.",
        claimed_run_id="private-claim", claimed_wake_reason="Check campaign results",
        next_action="Review new subscribers", progress_count=1000, history_count=1100,
        progress=[GoalProgress(summary=f"Review {i}", next_action=f"Old action {i}") for i in range(20)],
    )
    snapshot = goal_context(goal)
    assert [item["summary"] for item in snapshot["progress"]] == ["Review 17", "Review 18", "Review 19"]
    assert snapshot["earlier_progress_entries"] == 997
    assert snapshot["history_count"] == 1100
    assert snapshot["objective"] == goal.objective
    assert snapshot["summary"] == goal.summary and snapshot["known_facts"] == goal.known_facts
    assert snapshot["next_action"] == goal.next_action
    assert snapshot["current_run_reason"] == "Check campaign results"
    serialized = json.dumps(snapshot)
    assert "Old action" not in serialized and "private-claim" not in serialized
    assert not {"id", "conversation_id", "profile_id", "wake_id", "created_at", "claim_revision"} & snapshot.keys()
    assert len(serialized) < len(goal.model_dump_json()) / 2


def test_context_preserves_full_plan_and_every_pending_answer():
    goal = Goal(
        conversation_id="chat", profile_id="assistant", objective="Arrange an appointment",
        plan=[GoalStep(id="check", title="Check coverage", status="done", notes="Confirmed by insurer"),
              GoalStep(id="book", title="Book appointment", depends_on=["check"])],
        questions=[GoalQuestion(id="time", question="Which afternoon?", status="open", revision=2,
            reviewed_answer_count=1, choices=["Tuesday", "Wednesday"], answers=[
                GoalAnswer(question_id="time", question_revision=1, answer="Afternoons only"),
                *[GoalAnswer(question_id="time", question_revision=2, answer=f"Correction {i}") for i in range(5)],
            ])], blocking_question_ids=["time"],
    )
    snapshot = goal_context(goal)
    assert [GoalStep.model_validate(item) for item in snapshot["plan"]] == goal.plan
    question = snapshot["questions"][0]
    assert question["reviewed_answer_count"] == 1
    assert len(question["answers"]) == 6
    assert question["answers"][-1]["answer"] == "Correction 4"
    assert question["answers"][0]["question_revision"] == 1
    assert question["choices"] == ["Tuesday", "Wednesday"]
    assert snapshot["blocking_question_ids"] == ["time"]


async def test_hook_refreshes_state_after_small_mutation_receipt(tmp_path):
    from agent_core.agent_capabilities import AgentCapabilities
    from agent_core.control import ExecutionControl
    from agent_core.turn import ExecutionContext
    from goals import make_goal_tools

    store = GoalStore(tmp_path)
    goal = store.create("chat", "Grow newsletter", "assistant")
    goal = store.claim(goal.id, goal.wake_id, "owner")
    history = ConversationHistory(conversation_id="chat")
    hook = GoalContextHook(store, goal.id, "Base prompt", "owner", enabled=lambda: True)
    context = ExecutionContext(execution_id="root.test", conversation_id="chat", run_id="run",
                               event_sink=history, control=ExecutionControl())
    tools = {fn.__name__: fn for fn in make_goal_tools(store, goal.id, "root.test", claim_id="owner")}
    with context.bind("Test", AgentCapabilities([])):
        receipt = json.loads(await tools["update_goal_summary"]("Avoid paid ads; use library referrals.", goal.revision))
        assert "summary" not in receipt
        await hook.before_model(history, 1, "Test")
        state = json.loads(history.messages[0]["content"].split("(task data):\n")[1])
        assert state["summary"] == "Avoid paid ads; use library referrals."
        assert state["revision"] == receipt["revision"]
        assert json.loads(await tools["read_goal"]()) == state
