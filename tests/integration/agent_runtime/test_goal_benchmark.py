"""Verify the benchmark exercises the production goal runtime and scores effects."""
import hashlib
import pytest

from tests.benchmarks.goals.harness import Episode
from tests.benchmarks.goals.scenarios import SCENARIOS, scenario_by_id
from tests.benchmarks.goals.scoring import grade
from ._support import ScriptedProvider, call, reply


@pytest.mark.parametrize('premature', [False, True])
async def test_goal_benchmark_grades_real_runtime_effects(tmp_path, monkeypatch, premature):
    provider = ScriptedProvider()

    class Factory:
        @staticmethod
        def from_config(_config):
            return provider

    monkeypatch.setattr('tests.benchmarks.goals.harness._provider_class', lambda _: Factory)
    steps = [reply(calls=[call('read_goal')])]
    if not premature:
        receipt = 'receipt-' + hashlib.sha256(b'verified_deliverydevelopment').hexdigest()[:10]
        steps += [reply(calls=[call('inspect_service')]),
                  reply(calls=[call('perform_service_action', action='send', target='library')]),
                  reply(calls=[call('inspect_service', reference=receipt)])]
    steps += [reply(calls=[call('choose_next_action', action='complete', note='Checked the delivery receipt.',
                                outcome='Delivery verified')]), reply('Done')]
    provider.plan('contract', *steps)
    settings = {'provider': 'ollama', 'model': 'contract', 'base_url': 'http://unused',
                'split': 'development', 'max_calls': 20, 'max_iterations': 12,
                'context_window': 32000, 'run_timeout': 10, 'options': {'temperature': 0.2}}
    episode = Episode(scenario_by_id('verified_delivery'), settings, tmp_path / 'episode')
    data = await episode.run()
    assert data['harness_error'] is None
    assert any(e['type'] == 'goal' and e['data']['kind'] == 'wakeup' for e in data['events'])
    assert not any(e['type'] == 'goal' and e['data']['kind'] == 'state_notice' for e in data['events'])
    assert data['goal']['next']['kind'] == 'done'
    assert data['goal']['note'] == 'Checked the delivery receipt.'
    assert grade(data)['passed'] == (not premature)
    assert (tmp_path / 'episode' / 'state' / 'session-goals' / data['goal']['id'] / 'goal.json').exists()


async def test_goal_benchmark_drains_scheduler_completion_before_next_virtual_wake(tmp_path, monkeypatch):
    provider = ScriptedProvider()

    class Factory:
        @staticmethod
        def from_config(_config):
            return provider

    monkeypatch.setattr('tests.benchmarks.goals.harness._provider_class', lambda _: Factory)
    receipt = 'receipt-' + hashlib.sha256(b'scheduled_returndevelopment').hexdigest()[:10]
    provider.plan('contract',
        reply(calls=[call('read_goal')]),
        reply(calls=[call('perform_service_action', action='send', target='library')]),
        reply(calls=[call('update_goal', plan=[{'id': 'verify', 'title': f'Inspect {receipt} and verify delivery',
                                                'status': 'in_progress'}])]),
        reply(calls=[call('choose_next_action', action='schedule', at='2027-01-05T09:00:00+00:00',
                          note='Sent the announcement. Checking delivery tomorrow.')]),
        reply('Scheduled the delivery check.'),
        reply(calls=[call('read_goal')]),
        reply(calls=[call('inspect_service', reference=receipt)]),
        reply(calls=[call('choose_next_action', action='complete', note='Delivery confirmed.',
                          outcome='Delivery verified.')]),
        reply('Done'),
    )
    settings = {'provider': 'ollama', 'model': 'contract', 'base_url': 'http://unused',
                'split': 'development', 'max_calls': 20, 'max_iterations': 12,
                'context_window': 32000, 'run_timeout': 10, 'options': {'temperature': 0.2}}
    data = await Episode(scenario_by_id('scheduled_return'), settings, tmp_path / 'episode').run()
    assert data['harness_error'] is None
    assert len(data['runs']) == 2
    assert grade(data)['passed']
    assert not any(item['kind'] == 'stranded' for item in data['timeline'])


@pytest.mark.parametrize('identifier', [s.id for s in SCENARIOS])
async def test_every_benchmark_fixture_starts_with_one_due_goal(tmp_path, monkeypatch, identifier):
    class Factory:
        @staticmethod
        def from_config(_config):
            return ScriptedProvider()

    monkeypatch.setattr('tests.benchmarks.goals.harness._provider_class', lambda _: Factory)
    settings = {'provider': 'ollama', 'model': 'contract', 'base_url': 'http://unused',
                'split': 'development', 'max_calls': 20, 'max_iterations': 12,
                'context_window': 32000, 'run_timeout': 10, 'options': {'temperature': 0.2}}
    episode = Episode(scenario_by_id(identifier), settings, tmp_path / 'episode')
    try:
        episode.prepare()
        assert [goal.id for goal in episode.store.due(episode.clock.now)] == [episode.goal_id]
    finally:
        if episode.runtime:
            await episode.runtime.close()
        episode.stack.close()
