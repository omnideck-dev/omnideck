"""Goal transcript events are written once and restored from the conversation log."""

import asyncio
from datetime import datetime, timedelta, timezone

from agent_runtime import AgentRuntime
from conversations import load_events_jsonl
import pytest

from goals import GoalStateError, GoalStep, GoalStore
from goals._scheduling import GoalWorkSource

from ._support import call, reply


def transitions(events):
    return [event for event in events if event['type'] == 'goal'
            and event['data']['kind'] not in {'wakeup', 'state_notice'}]


async def test_goal_events_persist_once_for_live_idle_and_cold_transcript_reads(harness, tmp_path):
    h = harness
    h.profile()
    store = GoalStore(tmp_path / 'goals')
    await h.manager.close()
    h.manager = AgentRuntime(goal_store=store)
    goal = store.create('transitions', 'Keep the community calendar current', 'leaf')
    goal = store.update(goal.id, goal.revision, summary='A summary is not a lifecycle event')
    store.update(goal.id, goal.revision, plan=[GoalStep(id='dates', title='Review dates', status='in_progress')])
    store.pause(goal.id)
    with pytest.raises(GoalStateError):
        store.pause(goal.id)
    store.resume(goal.id)
    when = datetime.now(timezone.utc) + timedelta(hours=1)
    h.provider.plan('leaf', reply(calls=[call('read_goal')]), reply(calls=[call(
        'choose_next_action', action='schedule', at=when.isoformat(), note='Checked the calendar.',
    )]), reply('I will check again later.'))
    first = await h.run(conversation='transitions')
    events = load_events_jsonl('transitions')
    assert [e['data']['kind'] for e in transitions(events)] == ['started', 'paused', 'resumed', 'scheduled']
    assert len({e['id'] for e in events}) == len(events)
    assert all('goal_transition' not in str(request['messages']) for request in h.provider.requests)

    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(_request):
        entered.set()
        await release.wait()
        yield reply(calls=[call('read_goal')])

    h.provider.plan('leaf', hold, reply(calls=[call(
        'choose_next_action', action='complete', note='Verified every date.', outcome='Calendar verified',
    )]), reply('Done.'))
    source = GoalWorkSource(store, h.manager, enabled=lambda: True)
    completion = await source.pending(when + timedelta(seconds=1))[0].dispatch()
    await asyncio.wait_for(entered.wait(), 3)
    handle = h.manager.active_for_conversation('transitions')
    release.set()
    await completion
    live = [record.event async for record in handle.events()]
    live_goals = [event for event in live if event.payload.type == 'goal']
    assert [event.payload.data.kind for event in live_goals] == ['wakeup', 'completed']
    assert live_goals[0].payload.data.reason == 'planned'
    assert live_goals[0].payload.data.step == 'Review dates'
    # The wake already asks the model to read_goal; no second run-start notice.
    persisted = load_events_jsonl('transitions')
    milestones = transitions(persisted)
    assert [e['data']['kind'] for e in milestones] == ['started', 'paused', 'resumed', 'scheduled', 'completed']
    assert len({e['id'] for e in persisted}) == len(persisted)
    for event in [*first, *live]:
        if event.payload.type == 'goal':
            assert persisted.count(event.to_flat_dict('transitions')) == 1
    warm = await h.manager.conversations.load_conversation_resume_state('transitions')
    assert warm.events == persisted
    await h.manager.close()
    # Transcript recovery is independent of goal state and history files.
    store.delete_for_conversation('transitions')
    h.manager = AgentRuntime(goal_store=store)
    cold = await h.manager.conversations.load_conversation_resume_state('transitions')
    assert cold.events == persisted


async def test_existing_goal_history_is_not_backfilled_when_runtime_starts(harness, tmp_path):
    h = harness
    store = GoalStore(tmp_path / 'goals')
    goal = store.create('existing-goal', 'Keep the calendar current', 'leaf')
    store.pause(goal.id)
    original_history = store.read_history(goal.id)['entries']
    await h.manager.close()
    h.manager = AgentRuntime(goal_store=store)
    assert load_events_jsonl('existing-goal') == []
    store.resume(goal.id)
    events = load_events_jsonl('existing-goal')
    assert [e['data']['kind'] for e in events] == ['resumed']
    assert store.read_history(goal.id)['entries'][1:] == original_history
    await h.manager.close()
    h.manager = AgentRuntime(goal_store=store)
    snapshot = await h.manager.conversations.load_conversation_resume_state('existing-goal')
    assert snapshot.events == events
