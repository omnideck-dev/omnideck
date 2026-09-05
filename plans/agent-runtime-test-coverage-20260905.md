# Agent runtime regression coverage audit

Reviewed upstream base `6d02b60d` in the dedicated
`codex/agent-runtime-review-20260905` worktree. This change adds tests and CI
wiring plus a FakeProvider protocol extension; it does not implement the runtime redesign or fix the six deferred
defects from the runtime review.

## Assessment

The previous suite was not sufficient by itself for this refactor. It had good
coverage of individual helpers and substantial UI coverage, but runner unit
tests mocked `run_turn`, task executor tests mocked most composition, and SDK
unit tests used a compatibility fixture that rewrote history/event behavior.
Successful subagent execution was particularly weak in the unit baseline.
Several tests under `e2e` verified rendering of injected event streams or seeded
JSONL, rather than producing those events through the runtime.

Added **18 integration cases and 6 E2E cases**. The combined suite now provides
a useful behavioral baseline for incremental extraction of AgentFactory,
AgentExecutor, and shared AgentRunner/RunSession wiring. It is not proof that
every possible regression will be detected. The six existing defect behaviors
and new runtime policies need explicit intended-behavior tests as those policies
are implemented, rather than assertions that preserve known bugs.

## How the tests run

- **E2E:** Build the application image from the reviewed checkout. Start a fresh
  disposable container with `MOCK_LLM=1`; use the existing FakeProvider protocol
  (`say`, `spawn`, `bash`, `call_tool`, `slow`, `provider_fail`, `model_script`). Public HTTP APIs
  and Chrome/Playwright drive the real server, runner, SDK loop, tools, browser
  resources, persistence, and background routine scheduler. No live LLM is used.
- **Integration:** Real composition and execution, with external provider/browser
  I/O and storage locations substituted. The provider returns typed responses
  and exposes precise concurrency barriers and recorded request inputs. This
  catches failures that can be hidden by FakeProvider's cooperative directive
  planner, such as wrong tools, model options, or leaked child history.
- **Migrated presentation/resume E2E:** All agent event-stream mocks and seeded
  conversation logs have been removed from `tests/e2e`. These scenarios now run
  actual FakeProvider turns and resume the events produced by the runtime.
  Public metadata APIs prepare titles, pins, and legacy preview placement.

## Follow-up: migrate event fixtures to real execution

The ten migrated modules retain all **38 existing test cases**. This includes
their existing UI assertions and replaces their shared stream/log fixture setup:

| Modules | Cases | Execution now exercised |
| --- | --- | --- |
| `chat/test_entry_ordering.py` | 4 | Thinking/content deltas, actual tool execution, spawn footer, child activity ordering |
| `chat/test_nudge.py` | 2 | UI nudge to a live child, next model response, persistence, real completed-agent 409 |
| `chat/test_turn_rendering.py` | 5 | Live/resumed nudge and mid-turn compaction ordering; resumed real child tree |
| `chat/test_resume_attachments.py`, `chat/test_resume_previews.py` | 3 | Actual upload, write/send-file tools, persisted attachments/artifacts, legacy preview metadata |
| `conversations/test_conversation_list.py`, `conversations/test_conversation_management.py` | 20 | Real turns followed by search, switching, deletion, folders, pinning, renaming, archiving/restoring |
| `conversations/test_compaction_chip.py`, `conversations/test_multi_profile_compaction.py` | 3 | Actual compaction, calculated statistics/intent/summary, compaction across profile changes |
| `network/test_activity_compaction.py` | 1 | Actual child compaction, agent scoping, saved tokens, restored activity details |

`model_script` extends the existing FakeProvider where ordering tests need
thinking/content together with a tool request. Its input is validated as SDK
`ChatMessage` responses; it cannot supply application events or tool results.
The SDK still dispatches tools and produces all lifecycle, iteration, output,
nudge, compaction, and persistence events. Stable tool-call IDs select the next
response from actual history, including after compaction, without a mutable
script cursor. Five provider unit tests cover streaming, retries, progress after
compaction, new-turn reset, nested child directives, automatic skill loading,
and rejecting unreachable script steps.

`tests/e2e/_runtime.py` centralizes execution and public API fixture preparation.
The obsolete `network/_sse.py` event builder was deleted. A source audit found no
remaining E2E writes to `events.jsonl` or fabricated agent API responses. Existing
request observers/network interruption tests still forward real requests; the
software-update settings mock is unrelated to agent execution.

Migration verification:

| Check | Result |
| --- | --- |
| All cases in the ten migrated E2E modules | 38 passed |
| Full Python unit suite, including five new protocol tests | 1,945 passed |
| Provider unit + runtime integration selection | 128 passed |
| Complete E2E suite | 304 passed |
| `just check` | Passed |
| Test-case preservation audit against the reviewed base | All 38 names retained across 10 modules |

The initial full run exposed three fixture
assertion failures (uppercase profile names and zero savings from echo summaries);
the inputs/assertions were corrected while retaining positive-savings coverage.
Root compaction uses the existing `say` protocol for a concise summarizer reply;
child compaction summarizes enough real tool output to reduce its context.

## Behavior matrix

Paths below are relative to the worktree root.

| Behavior / proposed owner | Coverage and gap at initial review | Added coverage |
| --- | --- | --- |
| Admission, sequencing, replay / AgentRuntime, RunSession | Real API disconnect/replay and UI refresh/offline tests; manager unit tests | Real HTTP + manager + runner + loop for success, error, stop, conflict, invalid cursor, reconnect, cleanup, and next turn |
| Profile/options/capabilities / AgentFactory | UI profile edits and unit composition; entry-point wiring mostly mocked | Root/child/routine parameter matrix checks provider options, thinking, prompt, skill tools, browser assignment, and cleanup |
| History and attachments / AgentRunner | Real upload/resume UI plus history units | Decode and save actual attachment; force cold JSONL rehydration and check subsequent model input |
| Dynamic skills / AgentFactory, AgentState | Skill units and cooperative FakeProvider tool loading | Cross-turn skill persistence, changed profile baseline, and child-loaded skill/tool isolation from parent |
| Delegation / AgentRunner, AgentExecutor | Real nested network UI and child success/error cards; sparse child-loop unit coverage | Nested model-history isolation, correlation IDs, exact tool-result pairing, child failure recovery; new E2E checks one run and three persisted lifecycles |
| Concurrent children / AgentRuntime | UI grouped spawns do not establish execution overlap | Deterministic overlapping children with reversed completion order; assert independent state and paired parent results |
| Nudges / execution control | Existing child nudge E2E mocked both chat and nudge HTTP responses | Real root/child nudge E2E during a tool call; next model iteration uses the nudge and persists it under the correct agent |
| Cooperative stop / execution control | Real root streaming-stop UI | New child streaming-stop E2E asserts both stopped lifecycles and persisted partial output; integration verifies manager-to-SDK stop propagation and subsequent turn |
| Compaction / ContextManager, AgentExecutor | Existing compaction E2E used injected or seeded events | Actual root/child compaction through hooks with scoped summaries and intact tool pairs; E2E triggers real root compaction, persists it, and continues afterward |
| Output routing / RunSession | Real browser/terminal/artifact UI and persisted output scenarios | Root/child output fan-out into transcript, artifact index, browser/terminal stores with correct source identity and no duplicate events |
| Routines / TaskExecutor adapter | Existing E2E executed one task and checked output/UI/browser release | Actual scheduler + executor + store dependency success/failure and delegated file output; new E2E runs a two-task dependency graph whose first task delegates |
| Resource cleanup / RunSession, AgentRunner | Browser profile isolation/deletion and routine browser cleanup E2E; scope units | Agent and routine conversation exit hooks, success/error paths, and no stale stop/observer effects on subsequent turns |

## Earlier coverage-baseline verification

All of these completed successfully before the event-fixture migration above:

| Check | Result |
| --- | --- |
| Full Python unit suite (`just unit`) | 1,940 passed |
| Agent runtime integration contracts | 18 passed |
| Actual Chrome browser persistence integration | 3 passed |
| Full frontend suite (`just test-ui run`) | 763 passed in 118 files |
| Runtime/chat/routine/child UI E2E selection | 57 passed |
| Expanded API/routine/network/conversation/artifact/browser/profile E2E selection | 116 passed |
| Distinct E2E cases across those selections | 162 passed; 11 overlap |
| Focused unit + runtime integration coverage run | 644 passed |
| `just check` | Passed: lint, types, tool docs, release/workflow checks |
| Deliberate regression experiments | All 8 detected; source restored and 18 contracts rerun successfully |

The mutation experiment removed or broke event sequencing, artifact observation,
skill restoration, child history scoping, active tools passed to the provider,
manager stop propagation, routine dependency injection, and compaction summaries.
Every mutation produced behavioral test failures without collection/setup errors.
This is bounded evidence of detection, not an exhaustive mutation score.

Coverage below is from the same focused Python selection before/after adding
the integration contracts. It excludes the separately running E2E container.

| Component | Statement coverage before → after | Branches covered before → after |
| --- | --- | --- |
| `agent_runtime` | 276/326 → 290/326 | 57/84 → 68/84 |
| SDK child execution (`_spawn_agent.py`) | 33/117 → 107/117 | 3/40 → 27/40 |
| SDK turn execution/control | 223/234 → 224/234 | 72/80 → 72/80 |
| `TaskExecutor` | 61/73 → 69/73 | 6/16 → 13/16 |
| `TaskRunner` | 39/139 → 75/139 | 5/56 → 20/56 |

High helper coverage alone did not prove composition correctness. For example,
AgentState already had 100% statement coverage before these cross-entry tests.
TaskRunner still contains substantial uncovered notification/retry/recurrence
branches; the refactor's scheduling policy must not be inferred to be fully
covered by successful task-execution tests.

## Test execution and reproducibility

- `just integration` runs all integration tests, including the 18 agent runtime
  contracts and three browser-persistence cases. During focused debugging, the
  runtime subset can be selected with
  `just test-file tests/integration/agent_runtime/`.
- Pre-merge CI remains unchanged. Run the integration and relevant E2E suites
  manually before opening a runtime-refactor PR. The existing complete
  post-merge E2E image-release gate remains in place.
- `E2E_CONTAINER` and `E2E_PORT` now override the previous shared container/port.
  Another local test run replaced the default container during verification;
  unique names/ports resolved that collision. No runtime source fix was needed.
- Chrome also required a short temporary path for its Unix socket. A temporary
  symlink pointed into this worktree's ignored `.cache/runtime-review` directory.

Generated evidence is in `.cache/runtime-review`: `unit-all.log`, `ui-all.log`,
`runtime-check-final.log`, `runtime-final.xml`, `runtime-restored.xml`,
`browser-integration.xml`, `runtime-e2e.xml`, `runtime-e2e-expanded.xml`,
`coverage-before.json`, `coverage-after.json`, and `mutations/results.json`.
Early environment/setup failures were resolved before recording the passing
results above.

Migration evidence is in the same directory: `migration-final.xml` (38 cases),
`migration-sdk.xml` (128 cases), `migration-check-final.log`,
`migration-unit-all.log`, `migration-full-final.xml`, and
`migration-preserved-cases.json`. See
`tests/e2e/README.md` for the fixture boundary and reproduction commands.

## Remaining limits and migration rules

1. Hard budget enforcement, stop between queued tools, sibling cancellation,
   forced-cancellation status/partial output, routine retry side-effect safety,
   and self-dependent routine validation remain the six known defects. Their
   review probes are diagnostic artifacts, not passing regression contracts.
2. E2E uses deterministic model responses. It checks orchestration, not answer
   quality or live vendor API compatibility. Real compaction E2E exercises the
   summarization path with FakeProvider, not the quality of the summary.
3. Model request isolation/options and exact parallel overlap are asserted by
   integration tests; the current FakeProvider protocol does not expose those
   properties for direct E2E inspection.
4. Process-crash recovery of active runs, bounded replay retention, typed new
   execution outcomes, and new run-tree shutdown guarantees need tests alongside
   their implementation. Current reconnect coverage is network disconnect,
   not server-process restart.
5. Preserve these observable assertions while moving composition to the proposed
   classes. Adapt harness construction to new interfaces, keep real execution
   underneath, and run runtime contracts plus runtime E2E for each migration step.
6. Build future runtime E2E fixtures through FakeProvider and public APIs.
   Handwritten domain-event fixtures belong in isolated event/reducer unit tests.
