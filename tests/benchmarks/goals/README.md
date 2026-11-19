# Goal-following benchmark v1

This opt-in benchmark measures goal management across runs, rather than whether a
model produces plausible planning prose. Live agents run **only in containers**.
It uses the production runtime, internal goal skill, goal tools, file storage,
scheduler admission/recovery, event history and LLM compaction. Service and browser
I/O, storage locations and the clock are isolated. No real appointments, messages,
advertisements or purchases are made.

## Scenarios and scoring

| Scenario | Required behavior |
|---|---|
| verified_delivery | Send once, independently verify delivery, complete |
| revise_approach | Switch from an unavailable partner, revise the plan, preserve completed work and evidence |
| blocking_question | Ask for missing insurance, consume an answer delivered during the run, book correctly |
| partial_answers | Research while awaiting input, retain a partial answer, obtain the remaining requirement |
| corrected_answer | Use the latest corrected budget, run one campaign and verify its results |
| external_edit | Notice changed instructions during work and analyze instead of contacting anyone |
| scheduled_return | Save a useful wakeup, resume in the same chat, verify delayed delivery |
| history_recall | Recover an archived receipt from an older saved summary and verify it without resending |
| interrupted_action | Recover from an uncertain response and runtime restart without duplicating the effect |
| compaction | Preserve goal control and verify results through real LLM compaction |
| pause_cancel | Respect a pause, explicit resume and later cancellation |
| ongoing_campaign | Run five measured campaign cycles, save a handoff and schedule further work without completing |

Each episode includes all its runs, answers and wakeups. Pass requires every
scenario outcome/disposition check and no critical failure. External effects and
observations—not claims in the final response—establish success. Critical failures
include duplicate actions, premature completion, ignored user direction, booking
before required answers, and attempted spending above the user's limit. Simulated
services block such actions but record the **attempt** as a failure.

The main rate includes all scheduled trials: infrastructure errors remain visible
and count as unsuccessful trials. They are separately labeled, not silently retried
until a run passes. Normal production provider retries remain enabled and are
recorded. A comparison distinguishes infrastructure errors from behavioral
regressions. Five repeats are independent trials, **not best-of-five selection**.

Diagnostics include question updates, actual user interventions, goal/history
reads, compaction, wakeups, tool errors, model calls, tokens, wall time and available
cache measurements. Counts are not automatically penalties: extra reads or
questions may be useful. Current-fact cleanliness is diagnostic; external effects
and requirements decide the headline result. There is no subjective model judge.

## Run

Build the normal container image with the current source, then run without the app
entrypoint. The example reuses an existing image and mounts only the benchmark
source and its disposable output; rebuild the image when changing production code.

```bash
just build
mkdir -p .scratch/goal-benchmark
docker run --rm --add-host host.docker.internal:host-gateway \
  --entrypoint python -w /opt/omnideck \
  -v "$PWD/tests/benchmarks:/opt/omnideck/tests/benchmarks:ro" \
  -v "$PWD/.scratch/goal-benchmark:/results" \
  omnideck:latest -m tests.benchmarks.goals run \
  --provider ollama --model deepseek-v4.1-flash:cloud \
  --base-url http://host.docker.internal:11434 \
  --repeats 5 --workers 3 --output /results/baseline
```

Use a new output directory each time. `--scenarios` accepts comma-separated IDs;
`--repeats 1` is a smoke run. Default suite: **12 scenarios × 5 repeats = 60 episodes**.
Each episode has a maximum of 80 model calls (including compaction), 8 goal runs,
180 wall-clock seconds per run and a scenario-specific virtual-time horizon.
The normal 16-iteration runtime nudge remains in effect; the benchmark's call cap
is a hard stop. Default sampling is temperature 0.2, output limit 2500.

All native application provider adapters are selectable: Ollama, OpenAI Responses,
OpenAI-compatible endpoints, OpenRouter and Anthropic. Supply a direct endpoint or
omit `--base-url` to use a provider configured inside the container, including its
broker socket. Use normal credential configuration; do not put keys in command-line
arguments. `--options` accepts a JSON object of agent profile inference settings.
Only the Ollama/DeepSeek route is exercised in the initial baseline.

`--split holdout` uses withheld identity/budget variations. Reserve it from prompt
tuning; it is not a fundamentally different task distribution or proof of broad
generalization. The initial baseline uses development fixtures only.

## Outputs and comparison

Each run saves:

- `manifest.json`: suite/version hash, actual runtime source hash, model, options,
  budgets, scenario definitions, split and clock origin.
- `report.json` / `report.md`: overall and per-scenario results.
- `results.jsonl`: incrementally saved results, including failed episodes.
- Per-episode `episode.json`, `world.json`, `result.json`, exact normalized model
  requests/tool schemas and responses, and real goal/conversation files.

```bash
uv run python -m tests.benchmarks.goals compare \
  .scratch/goal-benchmark/baseline/report.json \
  .scratch/goal-benchmark/candidate/report.json \
  --output .scratch/goal-benchmark/comparison.json
```

Comparison rejects different suite hashes, splits, scenario sets, repetitions or
budgets. Runtime source/model/options may differ: those are the candidate changes.
Every episode pair is classified as improved, regressed, unchanged or affected by
infrastructure. Raw traces explain each result. A small difference is not a verdict;
repeat borderline comparisons and examine the actual failures. The reported Wilson
interval is descriptive: repeated scenarios are related, so it does not establish
confidence about all real-world goals.

## Fidelity and limits

The virtual clock starts on 2027-01-04. Wakes use the real scheduler `tick`; the
harness advances time to saved wakes. This tests wake decisions and admission, not
OS scheduling jitter, sleep/wake reliability or the background poller's real-time
accuracy. Keep the separate scheduler integration tests for those contracts.
After each run, the harness waits for the scheduler's completion observer before
advancing virtual time. Otherwise a finished run could still occupy admission
capacity during the next single test tick and falsely strand its valid wakeup.

Crash injection skips finalizing one claim, closes/recreates the runtime and
reloads file-backed state. The real claim recovery path then resumes it. This is a
controlled runtime-restart fault, not a process kill/power-loss test. Compaction
uses the candidate model through the real compaction strategy. The harness triggers
one compaction after three model iterations; normal runtime compaction also remains
enabled. Its calls and tokens count toward the episode budget. This isolates
recovery after compaction from repeated threshold-triggering behavior.

The harness substitutes browser I/O and exposes deterministic service tools.
It does not evaluate website navigation, actual dental networks or campaign ROI.
Fixture outcomes are hidden from model requests; the model has no filesystem tool
that can inspect grader code or simulation state.

Provider seeds are not assumed portable. Natural provider caching is retained;
cache warmth is not controlled and no billing savings are inferred. Zero normalized
cache counts cannot distinguish unsupported data from a real zero, so unavailable
measurements stay null. Costs stay null until a verifiable pricing/usage source is
provided. Wall time depends on concurrency and provider load.

Change scenario semantics or graders deliberately and bump the suite version;
never tune them to turn a candidate's valid failure into a pass. Use development
pilots to fix harness defects before freezing a baseline. Oracle unit tests include
false-success claims, duplicate attempts, delayed verification and incompatible
comparisons. Runtime integration tests prove the benchmark reaches real goal tools
and persisted events.

## Accepted five-tool reference

Larry accepted the five-tool design on 2026-10-25: `read_goal`, `update_goal`,
`read_goal_history`, `update_goal_questions`, and `set_goal_state`. The agent keeps
the current plan and summary accurate; the system preserves history. There is no
separately authored progress journal. State changes use a flat action selector
with action-specific runtime validation.

`baselines/deepseek-v4.1-flash-five-tools-v1.json` is the reference for future
comparisons. It records **59/60 (98.3%)**, versus **57/60 (95%)** for a freshly run
ten-tool baseline using the same corrected harness and model configuration.
Model calls fell from 952 to 782 and prompt tokens from 6,988,263 to 4,937,136.
The two premature-completion failures in the ten-tool run did not recur.

Keep the remaining question-resolution failure visible: one trial booked correctly
but left an answered question open. The model also supplied unsupported
`known_facts` arguments to `update_goal` ten times across seven episodes; the
existing generic dispatcher silently ignored them. The live suite did not exercise
the continue action; deterministic tests cover it. These are observed limitations,
not reasons to relax scoring or add speculative tools.

```bash
uv run python -m tests.benchmarks.goals compare \
  tests/benchmarks/goals/baselines/deepseek-v4.1-flash-five-tools-v1.json \
  .scratch/goal-benchmark/candidate/report.json
```

Full traces and the controlled comparison remain under
`.scratch/goal-benchmark/five-tools-20261025`. The saved reference retains the
configuration, source fingerprints, individual checks, and metrics. Future runs
must match its suite hash and comparison settings.

## Initial historical reference

`baselines/deepseek-v4.1-flash-v1.json` preserves the first full baseline: DeepSeek
Flash 4.1 through Ollama cloud, five independent trials per scenario, 60 total.
The strict result was **58/60 (96.7%)**. All simulated task outcomes were achieved;
two ongoing-goal trials omitted the required handoff summary, so ongoing management
scored **3/5**, while the other scenarios scored **55/55**. No critical violations or
infrastructure errors occurred. Holdout fixtures were not used.

The compact baseline includes configuration, source fingerprints, individual
checks and metrics. Full requests/events remain local under
`.scratch/goal-benchmark/baseline-v1`. Its harness predates the scheduler-completion
fix and summary-based recall fixture, so it is retained as historical evidence;
its different suite hash intentionally prevents direct comparison with new runs.
