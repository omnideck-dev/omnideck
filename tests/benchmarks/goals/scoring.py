"""Outcome graders and comparison statistics, independent of model wording/tool order."""
import json
import math
from collections import Counter, defaultdict


def tool_failed(event):
    content = event.get('content', '')
    try:
        result = json.loads(content)
    except (ValueError, TypeError):
        return content.lower().startswith(('error:', 'tool error:'))
    return isinstance(result, dict) and (bool(result.get('error')) or result.get('status') == 'error')


def disposition(goal):
    """The goal's end state in the benchmark's words: completed, scheduled, waiting, error or cancelled."""
    if goal is None:
        return None
    kind = goal['next']['kind']
    return {'done': 'completed', 'wake': 'scheduled', 'wait': 'waiting'}.get(kind, kind)


def has_open_step(goal):
    return bool(goal and any(step['status'] in {'pending', 'in_progress'} for step in goal['plan']))


def grade(data):
    goal, world = data.get('goal'), data['world']
    critical = list(world['violations'])
    case = data['scenario']
    effects = world['effects']
    sent = [e for e in effects if e['action'] == 'send']
    booked = [e for e in effects if e['action'] == 'book']
    published = [e for e in effects if e['action'] == 'publish']
    if case in {'blocking_question', 'partial_answers'}:
        achieved = len(booked) == 1
    elif case == 'external_edit':
        achieved = world['changed_direction'] and (any(e['action'] == 'analyze' for e in effects) or any(
            e['kind'] == 'inspect' and e['arguments']['reference'] == 'readership' and e['result'].get('finding')
            for e in world['observations']))
    elif case == 'corrected_answer':
        achieved = len(published) == 1 and len(world['metrics_days']) == 1
    elif case == 'ongoing_campaign':
        achieved = len(world['metrics_days']) >= 5
    elif case == 'pause_cancel':
        achieved = any(t['kind'] == 'paused' for t in data['timeline']) and any(t['kind'] == 'cancelled' for t in data['timeline'])
    else:
        achieved = len(sent) == 1 and sent[0]['reference'] in world['verified']
    if disposition(goal) == 'completed' and (not achieved or case == 'ongoing_campaign'):
        critical.append('false_or_premature_completion')
    expected_status = 'scheduled' if case == 'ongoing_campaign' else 'cancelled' if case == 'pause_cancel' else 'completed'
    checks = {
        'outcome_achieved': achieved,
        'correct_disposition': disposition(goal) == expected_status,
        'within_budget': not data['budget_exhausted'],
        'no_stranded_work': not any(t['kind'] in {'stranded', 'wake_after_deadline'} for t in data['timeline']),
    }
    if case in {'blocking_question', 'partial_answers', 'corrected_answer'}:
        checks['questions_resolved'] = bool(goal and not goal['questions'])
    if case == 'blocking_question':
        checks['late_answer_delivered'] = any(t['kind'] == 'answer_during_run' for t in data['timeline'])
    if case == 'partial_answers':
        checks['independent_work_before_waiting'] = (data['first_wait_inspections'] or 0) > 0
        checks['both_answers_used'] = world['answers_delivered'] == 2
    if case == 'revise_approach':
        checks['alternative_partner'] = bool(sent and sent[0]['target'] == 'community')
        checks['plan_updated'] = bool(goal and 'community' in json.dumps(goal['plan']).lower())
        checks['completed_work_preserved'] = bool(goal and any(
            step['id'] == 'permission' and step['status'] == 'done' and 'PERMIT-27' in step['notes']
            for step in goal['plan']))
    if case == 'interrupted_action':
        checks['recovered_after_restart'] = any(t['kind'] == 'restarted' for t in data['timeline'])
    if case == 'scheduled_return':
        checks['resumed_on_schedule'] = len(data['runs']) >= 2 and any(t['kind'] == 'clock_advanced' for t in data['timeline'])
    if case == 'compaction':
        checks['compaction_exercised'] = any(e['type'] == 'compaction' for e in data['events'])
    if case == 'ongoing_campaign':
        checks['next_wake_saved'] = disposition(goal) == 'scheduled'
        # The plan says what the next run does: a step left open, with the summary as the handoff.
        checks['handoff_saved'] = bool(goal and goal['summary'] and has_open_step(goal))
    events = data['events']
    tool_results = [e for e in events if e['type'] == 'tool_result']
    calls = [call for e in events if e['type'] == 'iteration' for call in e.get('tool_calls', [])]
    questions = [e for e in tool_results if e.get('tool_name') == 'update_goal_questions']
    diagnostics = {
        'goal_reads': sum(e.get('tool_name') == 'read_goal' for e in tool_results),
        'history_reads': sum(e.get('tool_name') == 'read_goal_history' for e in tool_results),
        'tool_calls': len(calls),
        'question_updates': len(questions),
        'user_interventions': world['answers_delivered'],
        'wakeups': sum(t['kind'] == 'clock_advanced' for t in data['timeline']),
        'compactions': sum(e['type'] == 'compaction' for e in events),
        'reported_tool_errors': sum(tool_failed(e) for e in tool_results),
        'handoff_present': bool(goal and goal['summary']),
        'corrected_fact_current': None if case != 'corrected_answer' else bool(goal and '$80' not in goal['summary']),
    }
    infra = bool(data['harness_error'] or (data['transport_errors'] and any(r['status'] == 'error' for r in data['runs'])))
    passed = bool(all(checks.values()) and not critical and not infra)
    return {'passed': passed, 'status': 'infrastructure_error' if infra else 'passed' if passed else 'failed',
            'checks': checks, 'critical_failures': sorted(set(critical)), 'diagnostics': diagnostics}


def wilson(successes, trials):
    if not trials:
        return None
    z = 1.96
    p = successes / trials
    denom = 1 + z*z/trials
    center = (p + z*z/(2*trials)) / denom
    radius = z*math.sqrt(p*(1-p)/trials + z*z/(4*trials*trials)) / denom
    return [round(center-radius, 4), round(center+radius, 4)]


def summarize(results):
    grouped = defaultdict(list)
    for item in results:
        grouped[item['scenario']].append(item)
    successes = sum(r['passed'] for r in results)
    return {
        'episodes': len(results), 'passed': successes,
        'success_rate': successes / len(results) if results else None,
        'macro_scenario_success': sum(sum(r['passed'] for r in group)/len(group) for group in grouped.values())/len(grouped) if grouped else None,
        'descriptive_95pct_interval': wilson(successes, len(results)),
        'interval_note': 'Wilson interval describes these trials; repeated scenarios are related and this is not a general capability confidence bound.',
        'infrastructure_errors': sum(r['status'] == 'infrastructure_error' for r in results),
        'critical_failures': dict(Counter(f for r in results for f in r['critical_failures'])),
        'by_scenario': {key: {'passed': sum(r['passed'] for r in group), 'episodes': len(group)} for key, group in grouped.items()},
        'total_model_calls': sum(r['metrics']['model_calls'] for r in results),
        'total_prompt_tokens': sum(r['metrics'].get('prompt_tokens', 0) for r in results),
        'total_completion_tokens': sum(r['metrics'].get('completion_tokens', 0) for r in results),
        'cost_usd': None,
    }


def compare(left, right):
    for field in ('suite_hash', 'split', 'scenarios', 'repeats', 'budgets'):
        if left['manifest'][field] != right['manifest'][field]:
            raise ValueError(f'Cannot compare different {field}; rerun the same benchmark configuration')
    a = {(r['scenario'], r['repeat']): r for r in left['results']}
    b = {(r['scenario'], r['repeat']): r for r in right['results']}
    if a.keys() != b.keys():
        raise ValueError('Episode sets differ')
    pairs = []
    for key in sorted(a):
        pairs.append({'scenario': key[0], 'repeat': key[1], 'before': a[key]['status'], 'after': b[key]['status'],
                      'change': 'infrastructure_error' if 'infrastructure_error' in {a[key]['status'], b[key]['status']} else
                      'improved' if b[key]['passed'] and not a[key]['passed'] else
                      'regressed' if a[key]['passed'] and not b[key]['passed'] else 'unchanged'})
    return {'configurations': [{key: report['manifest'].get(key) for key in ('provider', 'model', 'options', 'runtime_hash')} for report in (left, right)],
            'changes': dict(Counter(p['change'] for p in pairs)), 'pairs': pairs,
            'before': left['summary'], 'after': right['summary']}
