"""Goal dividers are written once, inside the run that caused them, and restored from the conversation log."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from agent_runtime import AgentRuntime
from conversations import load_events_jsonl
from goals import GoalRunExtension, GoalStateError, GoalStep, GoalWorkSource

from ._support import call, reply


def dividers(events):
    return [event['data']['kind'] for event in events if event['type'] == 'goal']


async def test_goal_events_persist_once_for_live_idle_and_cold_transcript_reads(harness):
    h = harness
    h.profile()
    store = h.goals
    goal = h.goal('transitions', 'Keep the community calendar current', 'leaf')
    goal = store.update(goal.id, goal.revision, summary='A summary is not a lifecycle event')
    store.update(goal.id, goal.revision, plan=[GoalStep(id='dates', title='Review dates', status='in_progress')])
    store.pause(goal.id)
    with pytest.raises(GoalStateError):
        store.pause(goal.id)
    store.resume(goal.id)
    assert load_events_jsonl('transitions') == []
    when = datetime.now(timezone.utc) + timedelta(hours=1)
    h.provider.plan('leaf', reply(calls=[call('read_goal')]), reply(calls=[call(
        'choose_next_action', action='schedule', at=when.isoformat(), note='Checked the calendar.',
    )]), reply('I will check again later.'))
    first = await h.run(conversation='transitions')
    events = load_events_jsonl('transitions')
    assert dividers(events) == ['scheduled']
    assert len({e['id'] for e in events}) == len(events)

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
    assert [event.payload.type for event in live][-2:] == ['goal', 'turn_end']
    persisted = load_events_jsonl('transitions')
    assert dividers(persisted) == ['scheduled', 'wakeup', 'completed']
    assert len({e['id'] for e in persisted}) == len(persisted)
    for event in [*first, *live]:
        if event.payload.type == 'goal':
            assert persisted.count(event.to_flat_dict('transitions')) == 1
    warm = await h.manager.conversations.load_conversation_resume_state('transitions')
    assert warm.events == persisted
    await h.manager.close()
    h.manager = AgentRuntime(extensions=[GoalRunExtension(store, enabled=lambda: True)])
    cold = await h.manager.conversations.load_conversation_resume_state('transitions')
    assert cold.events == persisted


async def test_user_goal_actions_write_no_chat_event(harness):
    h = harness
    store = h.goals
    goal = h.goal('existing-goal', 'Keep the calendar current', 'leaf')
    store.pause(goal.id)
    store.resume(goal.id)
    store.cancel(goal.id)
    store.reopen(goal.id)
    assert load_events_jsonl('existing-goal') == []
