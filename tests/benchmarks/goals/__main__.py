"""Run opt-in, isolated live-model episodes or compare saved results."""
import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import platform
from pathlib import Path

from .harness import Episode
from .scenarios import SCENARIOS, VERSION, scenario_by_id
from .scoring import grade, summarize, compare


def digest(paths):
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def run_one(identifier, repeat, settings, output):
    scenario = scenario_by_id(identifier)
    data = asyncio.run(Episode(scenario, settings, output).run())
    result = {'scenario': identifier, 'family': scenario.family, 'repeat': repeat,
              **grade(data), 'metrics': data['metrics'], 'artifact': str(output),
              'harness_error': data['harness_error'], 'transport_errors': data['transport_errors']}
    (Path(output) / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run')
    run.add_argument('--provider', required=True, choices=['ollama', 'openai', 'openai_compat', 'openrouter', 'anthropic'])
    run.add_argument('--model', required=True)
    run.add_argument('--base-url', help='Optional direct provider endpoint; otherwise use configured provider/broker')
    run.add_argument('--options', type=json.loads, default={'temperature': 0.2, 'num_predict': 2500})
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--scenarios', default=','.join(s.id for s in SCENARIOS))
    run.add_argument('--repeats', type=int, default=5)
    run.add_argument('--workers', type=int, default=3)
    run.add_argument('--split', choices=['development', 'holdout'], default='development')
    run.add_argument('--max-calls', type=int, default=80)
    run.add_argument('--max-iterations', type=int, default=16)
    run.add_argument('--context-window', type=int, default=32000)
    run.add_argument('--run-timeout', type=int, default=180)
    diff = commands.add_parser('compare')
    diff.add_argument('before', type=Path)
    diff.add_argument('after', type=Path)
    diff.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'compare':
        report = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
        if args.output:
            args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return
    if not Path('/.dockerenv').exists() and not Path('/run/.containerenv').exists():
        parser.error('Run live agents inside the project container; see the benchmark README.')
    if min(args.repeats, args.workers, args.max_calls, args.max_iterations, args.run_timeout, args.context_window) < 1:
        parser.error('Counts and budgets must be positive')
    selected = args.scenarios.split(',')
    if len(selected) != len(set(selected)) or set(selected) - {s.id for s in SCENARIOS}:
        parser.error('Select unique known scenario IDs')
    allowed = {'temperature', 'num_predict', 'top_k', 'top_p', 'repeat_penalty', 'think', 'reasoning_effort', 'reasoning_summary', 'thinking_budget'}
    if args.options.keys() - allowed:
        parser.error(f'Options must be agent profile settings: {sorted(allowed)}')
    args.output.mkdir(parents=True, exist_ok=False)
    settings = {key: getattr(args, key) for key in (
        'provider', 'model', 'base_url', 'options', 'split', 'max_calls', 'max_iterations', 'context_window', 'run_timeout')}
    root = Path(__file__).parent
    runtime_paths = [p for directory in ('goals', 'agent_runtime', 'agent_core', 'skills', 'conversations', 'providers') for p in Path(directory).rglob('*.py')]
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        commit = os.environ.get('BENCHMARK_COMMIT', 'unavailable')
    manifest = {
        'version': VERSION, 'suite_hash': digest(root.glob('*.py')),
        'started_at': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'provider_libraries': {name: version(name) for name in ('ollama', 'openai', 'anthropic')},
        'workers': args.workers,
        'runtime_hash': digest(runtime_paths), 'commit': commit,
        'provider': args.provider, 'model': args.model, 'options': args.options,
        'split': args.split, 'scenarios': selected, 'repeats': args.repeats,
        'budgets': {k: settings[k] for k in ('max_calls', 'max_iterations', 'context_window', 'run_timeout')},
        'scenario_specs': [asdict(scenario_by_id(s)) for s in selected],
        'clock_start': '2027-01-04T09:00:00+00:00', 'provider_seed': None,
        'cache_policy': 'Normal provider behavior; no cache flushing or claimed cold-cache isolation.',
    }
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(run_one, case, repeat, settings, args.output / f'{case}-{repeat}'): (case, repeat)
                for case in selected for repeat in range(args.repeats)}
        for job in as_completed(jobs):
            case, repeat = jobs[job]
            try:
                result = job.result()
            except Exception as exc:
                result = {'scenario': case, 'family': scenario_by_id(case).family, 'repeat': repeat,
                          'passed': False, 'status': 'infrastructure_error', 'checks': {}, 'critical_failures': [],
                          'metrics': {'model_calls': 0}, 'harness_error': {'type': type(exc).__name__, 'message': str(exc)}}
            results.append(result)
            with (args.output / 'results.jsonl').open('a') as stream:
                stream.write(json.dumps(result)+'\n')
            print(json.dumps({'scenario': case, 'repeat': repeat, 'status': result['status'],
                              'failed_checks': [k for k,v in result['checks'].items() if not v],
                              'critical': result['critical_failures'], 'error': result.get('harness_error')}), flush=True)
    results.sort(key=lambda r: (r['scenario'], r['repeat']))
    report = {'manifest': manifest, 'summary': summarize(results), 'results': results}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    lines = [f'# {VERSION}', '', f"Model: {args.provider} / {args.model}", '',
             f"Passed: {report['summary']['passed']}/{len(results)} episodes", '',
             '| Scenario | Passed |', '|---|---|']
    for case, stats in report['summary']['by_scenario'].items():
        lines.append(f"| {case} | {stats['passed']}/{stats['episodes']} |")
    lines += ['', 'Infrastructure errors remain visible and count as unsuccessful episodes.',
              'See report.json and episode traces for outcomes, critical failures and efficiency.',
              'Missing cache/cost measurements are unknown, not zero.']
    (args.output / 'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
