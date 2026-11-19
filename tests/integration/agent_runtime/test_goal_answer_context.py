"""Goal reply context survives real runtime delivery, persistence, and replay."""

import asyncio
import json

import pytest

from agent_core.context import APP_TEXT_PREFIX
from agent_core.context._view import build_llm_view
from agent_core.events import AgentEvent, UserMessagePayload
from agent_runtime import AgentRunRequest
from conversations import load_events_jsonl
from agent_runtime import QueuedMessage
from goals import (
    GoalAnswerRecorder, GoalAnswerSubmission, GoalQuestionChange, GoalRunTrigger, GoalStep, answer_message,
)
from goals._models import GoalChoice, local_time

from ._support import call, reply


def setup_scheduled_goal(h, conversation_id):
    """A goal that asked where to meet and scheduled its next run for 2099."""
    store = h.goals
    goal = h.goal(conversation_id, "Arrange a cleanup")
    goal = store.update(goal.id, goal.revision, plan=[
        GoalStep(id="forecast", title="Check the forecast for cleanup day", status="in_progress"),
    ])
    store.claim_for_turn(goal.id, "setup")
    goal = store.update_questions(goal.id, [GoalQuestionChange(id="place", question="Where should we meet?")],
                                  goal.revision, claim_id="setup")
    store.choose(goal.id, GoalChoice.model_validate({
        "action": "schedule", "at": "2099-01-01T09:00:00+00:00", "note": "Asked where to meet.",
    }), claim_id="setup", expected_revision=goal.revision)
    return store.finish_run(goal.id, "setup", "setup-run", "success")


@pytest.mark.parametrize("cause", ["answer", "message", "scheduled"])
async def test_goal_read_shows_the_next_action_except_in_the_run_that_holds_it(harness, tmp_path, cause):
    h = harness
    h.profile()
    store = h.goals
    h.manager.observe_events(GoalAnswerRecorder(store).handle_event)
    scheduled = setup_scheduled_goal(h, "scheduled-answer")
    submission = GoalAnswerSubmission(goal_id=scheduled.id, answers=[{
        "question_id": "place", "question_revision": 1, "answer": "Library entrance",
    }]) if cause == "answer" else None
    trigger = None
    if cause == "scheduled":
        assert store.claim(scheduled.id, scheduled.next.id, "scheduled-run", now=scheduled.next.at) is not None
        trigger = GoalRunTrigger(scheduled.id, scheduled.next.id, "scheduled-run", "planned",
                                 "Check the forecast for cleanup day")
    h.provider.plan("leaf", reply(calls=[call("read_goal")]), reply("Noted"))
    message, context, model_text = ("Continue", (), None) if submission is None else answer_message(
        scheduled.id, store.check_answers("scheduled-answer", submission))
    handle = await h.manager.start(AgentRunRequest(
        "scheduled-answer", message, None, "leaf", context=context, trigger=trigger, model_text=model_text,
    ))
    assert (await handle.wait()).status == "success"
    state = next(json.loads(m["content"]) for m in h.provider.requests[-1]["messages"]
                 if m["role"] == "tool" and '"objective"' in m.get("content", ""))
    assert not {"revision", "claim", "current_run_reason", "resume_at", "wake_reason"} & state.keys()
    if cause == "scheduled":
        assert "next_action" not in state
        assert h.provider.requests[0]["messages"][1]["content"] == f"{APP_TEXT_PREFIX}\nA goal run started. Read the goal."
    else:
        assert state["next_action"] == {"action": "schedule", "at": local_time(scheduled.next.at)}
        assert store.get(scheduled.id).next == scheduled.next
        assert not any(e["type"] == "goal" and e["data"]["kind"] == "wakeup"
                       for e in load_events_jsonl("scheduled-answer"))
    if cause == "answer":
        assert state["questions"][0]["answers"] == [{"answer": "Library entrance", "new": True}]


@pytest.mark.parametrize("during_run", [False, True])
@pytest.mark.parametrize("batched", [False, True])
async def test_goal_reply_context_reaches_provider_and_persisted_history(harness, tmp_path, during_run, batched):
    h = harness
    h.profile()
    store = h.goals
    h.manager.observe_events(GoalAnswerRecorder(store).handle_event)
    goal = h.goal("answer-context", "Plan a cleanup", 'leaf')
    store.claim_for_turn(goal.id, "setup")
    questions = [GoalQuestionChange(id="start_time", question="When should the cleanup start?")]
    if batched:
        questions.append(GoalQuestionChange(id="place", question="Where should we meet?"))
    goal = store.update_questions(goal.id, questions, goal.revision, claim_id="setup")
    store.choose(goal.id, GoalChoice.model_validate({
        "action": "wait_for_input", "question_ids": [question.id for question in questions], "note": "Asked.",
    }), claim_id="setup", expected_revision=goal.revision)
    store.finish_run(goal.id, "setup", "setup-run", "success")
    submission = GoalAnswerSubmission(goal_id=goal.id, answers=[{
        "question_id": "start_time", "question_revision": 1, "answer": "Saturday at 9 AM\n\nPlease finish before noon.",
    }, *([{"question_id": "place", "question_revision": 1, "answer": "Library entrance"}] if batched else [])])
    answer_text = "\n\n".join(answer.answer for answer in submission.answers)
    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting(_request):
        entered.set()
        await release.wait()
        yield reply("Working")

    if during_run:
        h.provider.plan("leaf", waiting, reply("Received your answer"))
    else:
        h.provider.plan("leaf", reply("Received your answer"))
    message, context, model_text = answer_message(goal.id, store.check_answers("answer-context", submission))
    handle = await h.manager.send(AgentRunRequest(
        "answer-context", "Continue" if during_run else message, None, "leaf",
        context=() if during_run else context, model_text=None if during_run else model_text,
    ))
    try:
        if during_run:
            await asyncio.wait_for(entered.wait(), 3)
            await h.manager.send(AgentRunRequest("answer-context", "Also check the weather", None, "leaf"))
            queued = await h.manager.send(AgentRunRequest("answer-context", message, None, "leaf", context=context,
                                                          model_text=model_text))
            assert isinstance(queued, QueuedMessage)
            assert all(not question.answers for question in store.get(goal.id).questions)
            release.set()
        assert (await asyncio.wait_for(handle.wait(), 5)).status == "success"
    finally:
        release.set()

    persisted = load_events_jsonl("answer-context")
    answers = [e for e in persisted if e["type"] == "user_message" and e["content"] == answer_text]
    assert len(answers) == 1
    assert answers[0]["context"] == [{
        "type": "goal_question", "goal_id": goal.id, "question_id": question.id,
        "question_revision": 1, "question": question.question, "answer": answer.answer,
    } for question, answer in zip(questions, submission.answers, strict=True)]
    wire = AgentEvent(payload=UserMessagePayload(
        type="user_message", content=answer_text, context=answers[0]["context"],
    )).model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    assert wire['payload']['context'] == answers[0]['context']
    blocks = [f'Question {question.id}: "{question.question}"\nAnswer: {answer.answer}'
              for question, answer in zip(questions, submission.answers, strict=True)]
    rendered = "[Answers to your goal questions]\n" + "\n\n".join(blocks)
    assert any(m.get("content") == rendered for m in h.provider.requests[-1]["messages"])
    assert any(m.get("content") == rendered for m in build_llm_view(persisted))
    assert any(e["type"] == "user_message" and e["content"] == answer_text for e in persisted)
    saved = store.get(goal.id)
    assert [question.answers[0].answer for question in saved.questions] == [answer.answer for answer in submission.answers]
    if during_run:
        ordinary = next(e for e in persisted if e.get("content") == "Also check the weather")
        assert ordinary["context"] == []
        assert answers[0]["nudge_id"] == queued.nudge_id
        assert not any(e["type"] in {"nudge_queued", "nudge_removed"} for e in persisted)


async def test_goal_write_after_compaction_needs_a_new_read(harness, monkeypatch):
    h = harness
    h.profile(context_window=1000, compaction_threshold=0.01)
    store = h.goals
    goal = h.goal('query-compaction', 'Private saved objective', 'leaf')

    async def unload(_model):
        pass

    monkeypatch.setattr('agent_runtime._compaction._unload_model', unload)
    h.provider.plan('leaf', reply(calls=[call('read_goal')]),
                    *[reply(calls=[call('read_goal_history')]) for _ in range(3)],
                    reply(calls=[call('update_goal', summary='From memory')]), reply('Ready'))
    h.provider.plan('summary', *[reply('Earlier work summarized.') for _ in range(20)])
    handle = await h.manager.start(AgentRunRequest('query-compaction', 'Continue', None, 'leaf'))
    assert (await handle.wait()).status == 'success'
    persisted = load_events_jsonl('query-compaction')
    assert any(e['type'] == 'compaction' for e in persisted)
    order = [e['type'] if e['type'] == 'compaction' else e.get('tool_name') for e in persisted
             if e['type'] == 'compaction' or e['type'] == 'tool_result']
    write = order.index('update_goal')
    assert 'compaction' in order[order.index('read_goal'):write]
    results = [e['content'] for e in persisted if e['type'] == 'tool_result' and e['tool_name'] == 'update_goal']
    assert results == ['Error: Read the goal with read_goal, then try again.']
    assert store.get(goal.id).summary == ''
    assert [e['content'] for e in persisted if e['type'] == 'user_message'] == ['Continue']
    assert not any(e['type'] == 'goal' for e in persisted)
