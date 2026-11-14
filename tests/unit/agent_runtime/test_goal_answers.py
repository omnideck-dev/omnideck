"""Goal answers are an ordinary user message, saved when the agent receives it."""

import asyncio
import logging

import pytest

from agent_core.events import AgentEvent, UserMessagePayload
from agent_core.turn import ExecutionResult
from agent_runtime import AgentRunRequest, AgentRuntime, QueuedMessage
from goals import GoalAnswerRecorder, GoalAnswerSubmission, GoalConflictError, GoalQuestionChange, GoalStore, answer_message

from tests.unit.goals.support import waiting


class AnswerRunner:
    """Publishes the opening message and reads queued messages when told to, like the real runner."""

    def __init__(self):
        self.started = asyncio.Event()
        self.read = asyncio.Event()
        self.release = asyncio.Event()
        self.session = None

    async def run(self, request, session):
        self.session = session
        session.add_event(AgentEvent(payload=UserMessagePayload(
            type="user_message", content=request.message, context=list(request.context),
        )))
        self.started.set()
        await self.read.wait()
        for message in session.root_context.control.drain_nudges():
            session.add_event(AgentEvent(payload=message))
        await self.release.wait()
        return ExecutionResult("success")


def setup_goal(tmp_path):
    store = GoalStore(tmp_path / "goals")
    goal = waiting(store, store.create("chat", "Find a dentist", "assistant"), "insurance",
                   "Which insurance plan?")
    answers = GoalAnswerSubmission(goal_id=goal.id, answers=[
        {"question_id": "insurance", "question_revision": 1, "answer": "Aetna Dental PPO"},
    ])
    return store, goal, answers


def answer_request(store, answers):
    message, context = answer_message(answers.goal_id, store.check_answers("chat", answers))
    return AgentRunRequest("chat", message, None, "assistant", context=context)


def runtime_for(store, runner):
    runtime = AgentRuntime(runner, goal_store=store)
    runtime.observe_events(GoalAnswerRecorder(store).handle_event)
    return runtime


async def test_answers_are_saved_when_they_open_a_run_and_not_before(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = runtime_for(store, runner)
    try:
        request = answer_request(store, answers)
        assert store.get(goal.id).questions[0].answers == []
        assert request.message == "Aetna Dental PPO"
        assert request.context[0].question == "Which insurance plan?"
        handle = await runtime.send(request)
        await runner.started.wait()
        saved = store.get(goal.id).questions[0]
        assert [answer.answer for answer in saved.answers] == ["Aetna Dental PPO"]
        assert saved.status == "open"
        runner.read.set()
        runner.release.set()
        await handle.wait()
    finally:
        runner.read.set()
        runner.release.set()
        await runtime.close()


async def test_queued_answers_are_saved_only_when_the_agent_reads_them(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = runtime_for(store, runner)
    try:
        handle = await runtime.send(AgentRunRequest("chat", "Continue useful work", None, "assistant"))
        await runner.started.wait()
        queued = await runtime.send(answer_request(store, answers))
        assert isinstance(queued, QueuedMessage)
        assert store.get(goal.id).questions[0].answers == []
        runner.read.set()
        await asyncio.sleep(0)
        assert [answer.answer for answer in store.get(goal.id).questions[0].answers] == ["Aetna Dental PPO"]
        read = [r.event.payload for r in handle._session.records
                if isinstance(r.event.payload, UserMessagePayload) and r.event.payload.nudge_id == queued.nudge_id]
        assert len(read) == 1 and read[0].context[0].question_id == "insurance"
        with pytest.raises(GoalConflictError, match="already sent"):
            store.check_answers("chat", answers)
        runner.release.set()
        await handle.wait()
    finally:
        runner.read.set()
        runner.release.set()
        await runtime.close()


async def test_answers_returned_by_stop_are_never_saved(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = runtime_for(store, runner)
    try:
        handle = await runtime.send(AgentRunRequest("chat", "Continue", None, "assistant"))
        await runner.started.wait()
        await runtime.send(answer_request(store, answers))
        handle.cancel()
        await handle.wait()
        assert store.get(goal.id).questions[0].answers == []
        assert store.check_answers("chat", answers)
    finally:
        runner.read.set()
        runner.release.set()
        await runtime.close()


async def test_refused_answer_save_is_logged_and_the_run_continues(tmp_path, caplog):
    store, goal, answers = setup_goal(tmp_path)
    runner = AnswerRunner()
    runtime = runtime_for(store, runner)
    try:
        handle = await runtime.send(AgentRunRequest("chat", "Continue", None, "assistant"))
        await runner.started.wait()
        await runtime.send(answer_request(store, answers))
        # The agent withdraws the question while the answer waits.
        current = store.get(goal.id)
        store.update_questions(goal.id, [GoalQuestionChange(id="insurance", status="withdrawn")],
                               current.revision, claim_id=current.claim.id)
        with caplog.at_level(logging.WARNING, logger="goals._answers"):
            runner.read.set()
            await asyncio.sleep(0)
        assert "were not saved" in caplog.text
        assert all(not question.answers for question in store.get(goal.id).questions)
        runner.release.set()
        assert (await handle.wait()).status == "success"
    finally:
        runner.read.set()
        runner.release.set()
        await runtime.close()


def test_check_answers_refuses_changed_questions_without_saving(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    answers.answers[0].question_revision = 2
    with pytest.raises(GoalConflictError, match="question changed"):
        store.check_answers("chat", answers)
    assert store.get(goal.id).questions[0].answers == []


def test_save_answers_skips_answers_already_saved(tmp_path):
    store, goal, answers = setup_goal(tmp_path)
    assert len(store.save_answers("chat", answers)) == 1
    assert store.save_answers("chat", answers) == []
    assert len(store.get(goal.id).questions[0].answers) == 1
