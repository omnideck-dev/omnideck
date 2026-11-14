"""Regression tests for benchmark oracles, fault recording and fair comparisons."""
import hashlib
import json
from copy import deepcopy
import pytest

from tests.benchmarks.goals.harness import Episode
from tests.integration.agent_runtime._support import ScriptedProvider, call, reply

from tests.benchmarks.goals.scenarios import scenario_by_id
from tests.benchmarks.goals.world import World, Clock
from tests.benchmarks.goals.scoring import grade, compare, summarize


def fixture_result():
    return {
        'scenario': 'verified_delivery', 'world': {'effects': [], 'observations': [], 'violations': [],
          'verified': [], 'metrics_days': [], 'answers_delivered': 0, 'changed_direction': False},
        'goal': {'next': {'kind': 'done', 'outcome': 'Delivered'}, 'paused': False,
                 'summary': 'Everything succeeded', 'questions': [], 'plan': []},
        'events': [], 'timeline': [], 'runs': [{'status': 'success'}],
        'budget_exhausted': False, 'first_wait_inspections': None,
        'harness_error': None, 'transport_errors': [],
    }


def test_successful_sounding_prose_cannot_pass_without_external_outcome():
    result = grade(fixture_result())
    assert not result['passed']
    assert 'false_or_premature_completion' in result['critical_failures']


def test_verified_effect_passes_without_matching_tool_order_or_prose():
    data = fixture_result()
    data['goal']['summary'] = 'A differently worded handoff'
    data['world']['effects'] = [{'action': 'send', 'reference': 'confirmation-9'}]
    data['world']['verified'] = ['confirmation-9']
    assert grade(data)['passed']
    data['world']['violations'] = ['duplicate_delivery']
    assert not grade(data)['passed']


def test_missing_cache_and_cost_are_not_inferred_as_zero():
    summary = summarize([])
    assert summary['cost_usd'] is None
    assert summary['success_rate'] is None
    assert summary['descriptive_95pct_interval'] is None


@pytest.mark.parametrize('field', ['suite_hash', 'split', 'scenarios', 'repeats', 'budgets'])
def test_comparison_rejects_incomparable_runs(field):
    report = {'manifest': {'suite_hash': 'v1', 'split': 'development', 'scenarios': ['a'], 'repeats': 5, 'budgets': {}},
              'results': [], 'summary': {}}
    other = deepcopy(report)
    other['manifest'][field] = 'different'
    with pytest.raises(ValueError, match=field):
        compare(report, other)


async def test_failed_response_can_hide_a_successful_send_and_duplicate_attempt_is_recorded(tmp_path):
    world = World(scenario_by_id('interrupted_action'), Clock(), tmp_path / 'world.json')
    inspect, act = world.tools()
    assert 'unknown' in await act('send', 'library')
    assert len(world.effects) == 1
    assert world.receipt in await inspect('outbox')
    assert 'duplicate_delivery' in await act('send', 'library')
    assert world.violations == ['duplicate_delivery']
    assert len(world.effects) == 1


async def test_simulator_records_forbidden_attempt_even_when_it_blocks_effect(tmp_path):
    world = World(scenario_by_id('external_edit'), Clock(), tmp_path / 'world.json')
    world.changed_direction = True
    _, act = world.tools()
    await act('send', 'library')
    assert world.effects == []
    assert world.violations == ['ignored_user_redirection']


async def test_service_delivery_requires_observation_after_ready_time(tmp_path):
    from datetime import timedelta
    world = World(scenario_by_id('scheduled_return'), Clock(), tmp_path / 'world.json')
    inspect, act = world.tools()
    await act('send', 'library')
    assert 'pending' in await inspect(world.receipt)
    assert not world.verified
    world.clock.now += timedelta(days=1)
    assert not world.verified
    assert 'confirmed' in await inspect(world.receipt)
    assert world.verified == [world.receipt]


def test_reading_existing_analysis_is_valid_without_an_extra_action_tool():
    data = fixture_result()
    data['scenario'] = 'external_edit'
    data['world']['changed_direction'] = True
    data['world']['observations'] = [{'kind': 'inspect', 'arguments': {'reference': 'readership'},
                                     'result': {'finding': 'Referrals convert best'}}]
    assert grade(data)['passed']


async def test_archived_receipt_requires_history_but_is_still_verifiable(tmp_path):
    world = World(scenario_by_id('history_recall'), Clock(), tmp_path / 'world.json')
    inspect, _ = world.tools()
    assert world.receipt not in await inspect('outbox')
    assert 'confirmed' in await inspect(world.receipt)


def ongoing_result(goal):
    data = fixture_result()
    data['scenario'] = 'ongoing_campaign'
    data['goal'] = goal
    data['world']['metrics_days'] = [1, 2, 3, 4, 5]
    return data


def test_ongoing_goal_needs_a_saved_wake_and_an_open_step():
    step = {'id': 'daily', 'title': 'Run the daily campaign and check results', 'status': 'in_progress', 'notes': ''}
    goal = {'next': {'kind': 'wake', 'id': 'w', 'at': '2027-01-10T09:00:00+00:00', 'reason': 'planned'},
            'paused': False, 'summary': 'Referrals convert best.', 'questions': [], 'plan': [step]}
    assert grade(ongoing_result(goal))['passed']
    closed = deepcopy(goal)
    closed['plan'][0]['status'] = 'done'
    assert not grade(ongoing_result(closed))['checks']['handoff_saved']
    done = deepcopy(goal)
    done['next'] = {'kind': 'done', 'outcome': 'Grew the list'}
    result = grade(ongoing_result(done))
    assert not result['checks']['next_wake_saved']
    assert 'false_or_premature_completion' in result['critical_failures']


def last_user(request):
    return next(message['content'] for message in reversed(request['messages']) if message['role'] == 'user')


def last_tool(request):
    return next(message['content'] for message in reversed(request['messages']) if message['role'] == 'tool')


async def test_scheduled_goal_comes_back_to_the_step_in_progress_and_its_notes(tmp_path, monkeypatch):
    provider = ScriptedProvider()

    class Factory:
        @staticmethod
        def from_config(_config):
            return provider

    monkeypatch.setattr('tests.benchmarks.goals.harness._provider_class', lambda _: Factory)
    receipt = 'receipt-' + hashlib.sha256(b'scheduled_returndevelopment').hexdigest()[:10]
    step = 'Inspect the delivery report and confirm delivery'
    notes = f'Sent to the library. Receipt {receipt}. The report is ready tomorrow at 9 AM.'

    async def resume_from_step(request):
        wakeup = last_user(request)
        assert wakeup.startswith('[System activity: goal wakeup]')
        assert f'Plan step: {step}' in wakeup
        yield reply(calls=[call('read_goal')])

    async def use_saved_notes(request):
        saved = json.loads(last_tool(request))
        assert saved['plan'][0] == {'id': 'confirm', 'title': step, 'status': 'in_progress', 'notes': notes}
        assert 'next_action' not in saved
        yield reply(calls=[call('inspect_service', reference=receipt)])

    provider.plan('contract',
        reply(calls=[call('read_goal')]),
        reply(calls=[call('perform_service_action', action='send', target='library')]),
        reply(calls=[call('update_goal', plan=[{'id': 'confirm', 'title': step, 'status': 'in_progress', 'notes': notes}])]),
        reply(calls=[call('choose_next_action', action='schedule', at='2027-01-05T09:00:00+00:00',
                          note='Sent the announcement. Checking the delivery report tomorrow.')]),
        reply('Scheduled the delivery check.'),
        resume_from_step,
        use_saved_notes,
        reply(calls=[call('update_goal', plan=[{'id': 'confirm', 'status': 'done'}])]),
        reply(calls=[call('choose_next_action', action='complete', note='The library confirmed delivery.',
                          outcome='Delivery confirmed by the library report.')]),
        reply('Done'),
    )
    settings = {'provider': 'ollama', 'model': 'contract', 'base_url': 'http://unused',
                'split': 'development', 'max_calls': 20, 'max_iterations': 12,
                'context_window': 32000, 'run_timeout': 10, 'options': {'temperature': 0.2}}
    data = await Episode(scenario_by_id('scheduled_return'), settings, tmp_path / 'episode').run()
    assert data['harness_error'] is None
    assert len(data['runs']) == 2
    assert data['goal']['next']['kind'] == 'done'
    assert data['goal']['plan'][0]['status'] == 'done'
    assert grade(data)['passed']
