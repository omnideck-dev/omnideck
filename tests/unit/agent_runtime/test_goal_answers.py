"""Answers enter the normal root run without competing with active goal work."""

import asyncio

import pytest

from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, RunConflictError
from goals import GoalAnswerSubmission, GoalQuestionChange, GoalStore


class AnswerRunner:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []
        self.session = None

    async def run(self, request, session):
        self.requests.append(request)
        self.session = session
        self.started.set()
        await self.release.wait()
        return ExecutionResult("success")


def setup_goal(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = store.create("chat", "Find a dentist", "assistant")
    goal = store.claim(goal.id, goal.wake_id, "setup")
    goal = store.update_questions(goal.id, [GoalQuestionChange(id="insurance", question="Which insurance plan?", status="open")], "", goal.revision, claim_id="setup")
    store.wait_for_input(goal.id, ["insurance"], claim_id="setup")
    store.release(goal.id, "setup")
    answers = GoalAnswerSubmission(goal_id=goal.id, answers=[{"question_id": "insurance", "question_revision": 1, "answer": "Aetna Dental PPO"}])
    return store, goal, answers


async def test_answer_submission_resumes_waiting_goal_with_canonical_question_and_answer(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        handle = await runtime.start(AgentRunRequest("chat", "client display text", None, "assistant", goal_answers=answers))
        await runner.started.wait()
        assert "[insurance] Which insurance plan?\nAetna Dental PPO" in runner.requests[0].message
        assert store.get(goal.id).status == "active"
        assert store.get(goal.id).questions[0].status == "open"
        assert len(store.get(goal.id).questions[0].answers) == 1
        runner.release.set()
        await handle.wait()
    finally:
        runner.release.set()
        await runtime.close()


async def test_live_answers_nudge_the_existing_root_and_conflicting_start_does_not_save_twice(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        handle = await runtime.start(AgentRunRequest("chat", "Continue useful work", None, "assistant"))
        await runner.started.wait()
        runtime.answer_goal_during_run("chat", answers)
        assert runtime.active_for_conversation("chat").run_id == handle.run_id
        assert len(runner.requests) == 1
        assert "Aetna Dental PPO" in runner.session.root_context.control.drain_nudges()[0]
        with pytest.raises(RunConflictError):
            await runtime.start(AgentRunRequest("chat", "answer", None, "assistant", goal_answers=answers))
        assert len(store.get(goal.id).questions[0].answers) == 1
        runner.release.set()
        await handle.wait()
    finally:
        runner.release.set()
        await runtime.close()


async def test_answering_explicitly_paused_goal_does_not_acquire_it(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    store.pause(goal.id)
    runner = AnswerRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        handle = await runtime.start(AgentRunRequest("chat", "answer", None, "assistant", goal_answers=answers))
        await runner.started.wait()
        assert store.get(goal.id).status == "paused"
        assert store.get(goal.id).claimed_run_id is None
        assert not store.due()
        runner.release.set()
        await handle.wait()
    finally:
        runner.release.set()
        await runtime.close()


async def test_answers_rejected_during_execution_cleanup_are_not_saved(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = AgentRuntime(runner, goal_store=store)
    try:
        handle = await runtime.start(AgentRunRequest("chat", "Continue", None, "assistant"))
        await runner.started.wait()
        runner.session.root_context.control.accepting_nudges = False
        with pytest.raises(ValueError, match="no longer running"):
            runtime.answer_goal_during_run("chat", answers)
        assert store.get(goal.id).questions[0].answers == []
        runner.release.set()
        await handle.wait()
    finally:
        runner.release.set()
        await runtime.close()
