"""Goal reply context survives real runtime delivery, persistence, and replay."""

import asyncio
import json

import pytest

from agent_core.context import GOAL_STATE_PREFIX
from agent_core.context._view import build_llm_view
from agent_core.events import AgentEvent, UserMessagePayload
from agent_runtime import AgentRunRequest, GoalRunTrigger
from conversations import load_events_jsonl
from agent_runtime import QueuedMessage
from goals import (
    GoalAnswerRecorder, GoalAnswerSubmission, GoalQuestionChange, GoalStep, GoalStore, answer_message,
)
from goals._models import GoalChoice, local_time

from ._support import call, reply


def setup_scheduled_goal(store, conversation_id):
    """A goal that asked where to meet and scheduled its next run for 2099."""
    goal = store.create(conversation_id, "Arrange a cleanup", "leaf")
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
    store = GoalStore(tmp_path / "goals")
    h.manager._goal_store = store
    h.manager._runner.goal_store = store
    h.manager.observe_events(GoalAnswerRecorder(store).handle_event)
    scheduled = setup_scheduled_goal(store, "scheduled-answer")
    submission = GoalAnswerSubmission(goal_id=scheduled.id, answers=[{
        "question_id": "place", "question_revision": 1, "answer": "Library entrance",
    }]) if cause == "answer" else None
    trigger = None
    if cause == "scheduled":
        assert store.claim(scheduled.id, scheduled.next.id, "scheduled-run", now=scheduled.next.at) is not None
        trigger = GoalRunTrigger(scheduled.id, scheduled.next.id, "scheduled-run", "planned",
                                 "Check the forecast for cleanup day")
    h.provider.plan("leaf", reply(calls=[call("read_goal")]), reply("Noted"))
    message, context = ("Continue", ()) if submission is None else answer_message(
        scheduled.id, store.check_answers("scheduled-answer", submission))
    handle = await h.manager.start(AgentRunRequest(
        "scheduled-answer", message, None, "leaf", context=context, goal_trigger=trigger,
    ))
    assert (await handle.wait()).status == "success"
    state = next(json.loads(m["content"]) for m in h.provider.requests[-1]["messages"]
                 if m["role"] == "tool" and '"objective"' in m.get("content", ""))
    assert not {"revision", "claim", "current_run_reason", "resume_at", "wake_reason"} & state.keys()
    if cause == "scheduled":
        assert "next_action" not in state
        assert "Plan step: Check the forecast for cleanup day" in h.provider.requests[0]["messages"][1]["content"]
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
    store = GoalStore(tmp_path / "goals")
    h.manager._goal_store = store
    h.manager._runner.goal_store = store
    h.manager.observe_events(GoalAnswerRecorder(store).handle_event)
    goal = store.create("answer-context", "Plan a cleanup", "leaf")
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
    message, context = answer_message(goal.id, store.check_answers("answer-context", submission))
    handle = await h.manager.send(AgentRunRequest(
        "answer-context", "Continue" if during_run else message, None, "leaf",
        context=() if during_run else context,
    ))
    try:
        if during_run:
            await asyncio.wait_for(entered.wait(), 3)
            await h.manager.send(AgentRunRequest("answer-context", "Also check the weather", None, "leaf"))
            queued = await h.manager.send(AgentRunRequest("answer-context", message, None, "leaf", context=context))
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
    # The live stream omits defaults. Its nested discriminators must still
    # identify question references, just like persisted conversation events.
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


async def test_goal_query_notice_survives_compaction_without_creating_user_messages(harness, monkeypatch, tmp_path):
    from ._support import call

    h = harness
    h.profile(context_window=1000, compaction_threshold=0.01)
    store = GoalStore(tmp_path / 'goals')
    h.manager._goal_store = store
    h.manager._runner.goal_store = store
    store.create('query-compaction', 'Private saved objective', 'leaf')

    async def unload(_model):
        pass

    monkeypatch.setattr('agent_runtime._compaction._unload_model', unload)
    h.provider.plan('leaf', *[reply(calls=[call('read_goal')]) for _ in range(4)], reply('Ready'))
    h.provider.plan('summary', *[reply('Earlier work summarized.') for _ in range(20)])
    handle = await h.manager.start(AgentRunRequest('query-compaction', 'Continue', None, 'leaf'))
    assert (await handle.wait()).status == 'success'
    requests = [r['messages'] for r in h.provider.requests if r['model'] == 'leaf']
    assert 'Private saved objective' not in str(requests[0])
    assert requests[0][-1]['content'].startswith(GOAL_STATE_PREFIX)
    assert 'Read the goal before goal work' in requests[0][-1]['content']
    assert any('Earlier messages were compacted' in str(r[-1].get('content', '')) for r in requests[2:])
    assert any('Private saved objective' in m.get('content', '') for r in requests[1:] for m in r if m['role'] == 'tool')
    persisted = load_events_jsonl('query-compaction')
    assert any(e['type'] == 'compaction' for e in persisted)
    assert any(e['type'] == 'goal' and e['data']['kind'] == 'state_notice' and e['data']['reason'] == 'compacted' for e in persisted)
    assert GOAL_STATE_PREFIX in str(build_llm_view(persisted))
    assert [e['content'] for e in persisted if e['type'] == 'user_message'] == ['Continue']
    assert len([e for e in persisted if e['type'] == 'goal' and e['data']['kind'] == 'state_notice']) == len([e for e in persisted if e['type'] == 'compaction']) + 1
