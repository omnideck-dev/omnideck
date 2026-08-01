# Resumable Agent Runs

## Goal

An agent run for the currently open conversation must keep running when its
HTTP client disconnects unintentionally. The same conversation can later find
the active run and receive the events it missed.

The first implementation covers:

- a laptop sleeping or closing its lid;
- temporary network loss;
- refreshing or reopening the browser on the active conversation.

It does not add background execution across intentional conversation switches.
New Chat and opening a different conversation may keep their current explicit
stop behavior, so this slice does not introduce concurrent interactive chat
agent runs. Resuming work after the application process exits is also out of
scope because the in-flight provider request and tool coroutines cannot be
reconstructed from the conversation event log.

## Previous ownership problem

The previous call chain was:

```text
POST /api/chat
  -> chat_handler()
  -> stream_events()
  -> handle_user_message() async generator
       -> creates producer_task
       -> turn execution
```

The legacy `handle_user_message()` adapter owned `producer_task`. When
`stream_events()` stops
iterating after a failed socket write, Python closes the async generator. Its
`finally` block cancels `producer_task`, so transport lifetime and run lifetime
are the same thing.

That queue between execution and the response also had two limitations:

- it supports only the client that started the turn;
- it has no cursor or retained events, so a later client cannot recover a gap.

## Proposed ownership

```text
                         +--------------------------+
Any channel -----------> | ActiveRunManager         |
                         |                          |
                         | ActiveRun                |
                         |  - background task       |
                         |  - ordered replay log    |
                         |  - completion state      |
                         |  - stop event            |
                         +-------------+------------+
                                       |
                           AgentRunner.run(emit)
                                       |
                              sdk.turn.run_turn()
                                       |
                           ConversationHistory fanout
                           /             |          \
                    persistence       sidecars     ActiveRun.append
                                                     |
                              +----------------------+------------------+
                              |                                         |
                     initial POST response                    reconnect GET response
```

The manager is process-scoped and holds a strong reference to every running
task. HTTP responses and future channels are subscribers. Closing a subscriber
does not stop the run.

## Runtime types and contracts

Add a top-level `agent_runtime` package with these public types:

```python
@dataclass(frozen=True)
class AgentRunRequest:
    conversation_id: str
    message: str
    data: Sequence[Data] | None
    profile_id: str | None


@dataclass(frozen=True)
class SequencedEvent:
    run_id: str
    seq: int
    event: AgentEvent


@dataclass(frozen=True)
class AgentRunInfo:
    run_id: str
    conversation_id: str
    last_seq: int


class AgentRunner:
    def __init__(self, conversation_loader: ConversationLoader) -> None: ...

    async def run(
        self,
        request: AgentRunRequest,
        *,
        emit: EventSink,
        stop_event: asyncio.Event,
    ) -> None: ...


class ActiveRunManager:
    async def start(self, request: AgentRunRequest) -> AgentRunInfo: ...
    def active_for_conversation(self, conversation_id: str) -> AgentRunInfo | None: ...
    def get(self, run_id: str) -> AgentRunInfo | None: ...
    def subscribe(
        self, run_id: str, *, after_seq: int
    ) -> AsyncGenerator[SequencedEvent, None]: ...
    def request_stop(self, conversation_id: str) -> bool: ...
    async def close(self) -> None: ...
```

The actual public return type is the read-only `AgentRunInfo`; `_ActiveRun`
remains private mutable manager state.

### Run identity and admission

The manager creates a UUID `run_id` when it accepts a new run. The frontend
does not automatically retry the start POST after a transport failure; it asks
the resume API whether that conversation has an active run and attaches to it.

`ActiveRunManager.start()` applies these rules atomically:

1. Starting a run while that conversation already has one active is a
   conflict.
2. The conversation is reserved before any awaited setup work, preventing two
   concurrent POSTs from both passing the active check.

The manager, not `sdk.turn.is_turn_active()`, is the application
admission-control authority. `is_turn_active()` becomes the lower-level
execution-state signal used by the SDK, cache eviction, and nudge machinery.

### Sequence and replay

Every event appended to an `_ActiveRun` receives a monotonically increasing
integer `seq`, beginning at 1. The existing `AgentEvent.id` remains the stable
domain-event identity; `seq` is only a transport cursor within one run.

Wire records keep the existing envelope shape and add two top-level fields:

```json
{
  "run_id": "run_...",
  "seq": 17,
  "id": "evt_...",
  "agent_id": "root.agent.1",
  "payload": {"type": "content", "content": "hello"}
}
```

The client reconnects with the last fully processed sequence:

```text
GET /api/chat/runs/{run_id}/events?after=17
```

The subscription first yields retained records with `seq > 17`, then waits for
new records until the runner finishes. Registering the waiter and inspecting
the replay list must be atomic with respect to `append()` so an event cannot
fall between replay and live delivery.

The implementation uses a shared append-only record list plus one
`asyncio.Event` per waiting subscriber. Subscriber queues do not hold event
copies: a slow or disconnected channel must not create another unbounded queue.
All mutation occurs synchronously on the process event-loop thread.

### Replay retention

Keep all transcript-critical events for the lifetime of an active run:

- `content`
- persisted canonical events such as `user_message`, `iteration`,
  `tool_result`, lifecycle, compaction, file output, and error events
- `turn_end`

Large replaceable workspace events need a separate retention policy because
historical conversation logs were dominated by screenshots:

- browser and terminal state are already restored from bounded sidecars;
- only the latest generation preview for a `gen_id` needs replay;
- audio playback and other one-shot presentation effects should not replay
  after a full page reload.

For the first slice, retain the complete stream for one agent run. This is the
simplest correct replay behavior. Byte caps and event coalescing are a follow-up
only if measurements show that one run creates unacceptable memory use.

Retain replay records only while the run is active. When `AgentRunner.run()`
returns, remove the run from manager lookup immediately. Subscribers that were
already attached keep their captured reference long enough to consume every
event the runner emitted, including `turn_end`; new attach requests receive
`404` and fall back to persisted conversation state.

### Completion and failures

Domain completion belongs to `AgentRunner`, not `ActiveRunManager`.

- Normal turns already publish exactly one `turn_end` from `turn_scope()`.
- `ToolLoopError` already publishes its user-facing error before unwinding and
  must not gain a duplicate generic error.
- The concrete runner subscribes persistence and the supplied event sink, then
  enters `turn_scope()` before the remaining fallible setup.
- Exceptions are translated to user-facing events inside that scope, allowing
  `turn_scope()` to remain the single owner of `turn_end`.

The manager neither imports domain error types nor synthesizes `error` or
`turn_end`. It marks the run complete when the runner exits, wakes every
subscriber, logs an unexpected uncaught exception, and prunes the run. This
also allows future non-chat runners to define their own event lifecycle.

## Applying the design to the current message handler

Move the current generator's application setup behind `AgentRunner.run()`:

```python
async def run(
    self,
    request: AgentRunRequest,
    *,
    emit: EventSink,
    stop_event: asyncio.Event,
) -> None:
    # load/create conversation and perform the existing setup
    # publish through emit; enter turn_scope early
```

The runner must not:

- create its own background task;
- create a transport queue;
- yield transport records;
- react to subscriber disconnects.

It remains responsible for agent setup, persistence subscribers, sidecar
subscribers, `turn_scope()`, `agent_span()`, and `sdk.turn.run_turn()`. Its
stream observer changes from the per-request queue handler to the synchronous
`_ActiveRun.append` callback supplied as `emit`.

Subscriptions remain ordered with persistence before the active-run callback.
This gives resume a useful invariant: if a canonical event is visible in
`events.jsonl`, that same event can be resolved to a run sequence.

`server/message_handler.py` was removed after application setup moved into
`agent_runtime` and the routes began using the manager directly.

| Current `handle_user_message()` responsibility | New owner |
| --- | --- |
| profile/conversation validation and attachment preparation | `AgentRunner` |
| `_queue_handler` | removed; `_ActiveRun.append` is the history observer |
| `asyncio.create_task(_producer())` | `ActiveRunManager.start()` |
| `while queue.get(): yield event` | `ActiveRunManager.subscribe()` |
| cancel producer in generator `finally` | removed |
| avoid duplicate `ToolLoopError` output | `AgentRunner`, inside `turn_scope()` |
| translate setup failure and emit `turn_end` | `AgentRunner` and `turn_scope()` |

### Early stop

There is a race today if Stop arrives after the manager reserves a run but
before `turn_scope()` registers its SDK stop event. The stop would be lost.

Let `turn_scope()` accept an optional externally created `asyncio.Event`.
`_ActiveRun` creates that event at reservation time; `AgentRunner` passes it
into `turn_scope()`. The SDK registers the same object, so an early manager stop
and the existing `check_stop()` calls observe one signal.

Add a `check_stop()` checkpoint before the first model request. Today the first
check during streaming happens after a provider delta, so a pre-set stop event
could otherwise still start an unnecessary provider request.

## Applying the design to channel adapters

### Initial HTTP start

Keep the existing endpoint and response style initially:

```text
POST /api/chat
```

The HTTP adapter:

1. validates and translates the request into `AgentRunRequest`;
2. calls `manager.start()` and receives its generated `run_id`;
3. streams `manager.subscribe(run_id, after_seq=0)`.

A failed `resp.write()` ends only this subscription. It never cancels the
manager's task. The JSONL writer serializes `SequencedEvent` and does not
manufacture domain events.

### Reattach

Add:

```text
GET /api/chat/runs/{run_id}/events?after={seq}
```

Responses:

- `200`: replay followed by live records; EOF when the run completes;
- `404`: unknown or completed run; reload persisted conversation state;
- `409 replay_unavailable`: reserved for future bounded replay;
- `400`: malformed or future cursor.

This stays JSONL-over-fetch. The route remains part of the browser's HTTP chat
adapter; other channels consume `agent_runtime` directly. A generic
`/api/agent-runs` resource is deferred until a real external HTTP consumer
needs it.

### Conversation resume

Extend the existing conversation resume response with:

```json
{
  "active_run": {
    "run_id": "run_...",
    "status": "running",
    "last_seq": 23,
    "resume_after_seq": 18
  }
}
```

`resume_after_seq` is the sequence of the newest event in the persisted
snapshot that also belongs to this active run. Reattaching after that cursor
avoids duplicating restored canonical events while replaying later deltas.

The lookup uses stable `AgentEvent.id` values:

1. load the persisted event and sidecar snapshot as today;
2. scan backward for the newest ID indexed by the active run;
3. return its sequence, or 0 if the active run has not persisted an event yet.

If the manager has reserved a run before its first event reaches disk, resume
returns an empty snapshot plus that active run instead of a false `404`.

Events emitted after the snapshot necessarily have a higher sequence and close
the snapshot/tail race when replayed by the attach endpoint.

### Stop and shutdown

`POST /api/chat/stop` asks the manager to set the run's stop event. It does not
cancel the task.

Register the shared runtime on the application rather than in a route module
global:

```python
runner = build_agent_runner(...)
app[ACTIVE_RUN_MANAGER_KEY] = ActiveRunManager(runner)
app.on_cleanup.append(_stop_active_run_manager)
```

On application shutdown:

1. reject new starts;
2. set every active run's stop event;
3. wait for a bounded grace period;
4. cancel tasks that cannot stop cleanly.

Backend restart continuity remains explicitly out of scope.

## Frontend boundary

The frontend:

- retain the manager-generated `run_id` from stream records;
- advance `lastSeq` after each sequenced record is processed;
- reconnect the GET stream with bounded exponential backoff;
- keep the UI streaming while reconnecting instead of treating transport EOF
  as run completion;
- set idle only after `turn_end` or proof there is no active run;
- use `active_run.resume_after_seq` when reopening a running conversation;
- keep the current intentional-stop behavior for New Chat and conversation
  switching.

The stream connection is aborted on component teardown without sending Stop,
so a page refresh only removes that browser subscriber. Conversation restore
applies the persisted agent/workspace snapshot before replay begins; this
prevents a fast replay record from being erased by the restore resets. If the
run is pruned between discovery and attach, the client refetches the durable
event and sidecar snapshot and applies only the missing event IDs.

## Implementation slices

Before and after the `AgentRunner` implementation, run the focused E2E
regression gate:

```text
just e2e tests/e2e/api/agent_runs/ \
         tests/e2e/chat/test_run_reconnect.py \
         tests/e2e/chat/test_stop.py \
         tests/e2e/chat/test_upload.py \
         tests/e2e/chat/test_multi_turn.py \
         tests/e2e/chat/test_provider_errors.py \
         tests/e2e/chat/test_resume.py
```

`tests/e2e/api/agent_runs/` inspects the real JSONL and resume APIs rather
than relying on rendered UI. It locks down lifecycle ordering, exactly one
terminal event, unique event IDs, append-only multi-run persistence, profile
persistence, runner-setup failure behavior, and provider-error identity across
the live and persisted streams. `test_stop.py` additionally verifies the
stopped root lifecycle and partial iteration on disk. The remaining focused
files cover attachments, sidecars across turns, visible failure handling, and
conversation restoration.

This baseline gate protects existing execution behavior. The API suite also
closes an initial stream during slow generation, reconnects after the last
processed sequence, and verifies replay plus live completion without gaps.

1. **Runtime manager core**
   - `AgentRunRequest`, `AgentRunner`, `ActiveRunManager`, per-conversation
     reservation, replay subscription, early stop, and cleanup.
   - Unit tests with an injected fake runner.
2. **AgentRunner implementation**
   - move task-neutral setup out of the HTTP message handler;
   - pass the manager stop event through `turn_scope()`;
   - preserve failure and terminal-event behavior in the runner.
3. **HTTP start and attach**
   - add `run_id` and `seq` wire metadata;
   - make disconnect subscriber-only;
   - route and disconnect integration tests.
4. **Resume integration**
   - active-run snapshot and persisted-event cursor resolution.
5. **Frontend reconnect**
   - cursor tracking, retry state machine, refresh restore/reattach.
6. **End-to-end tests**
   - disconnect, laptop sleep simulation, reload, completion-race fallback,
     and explicit Stop coverage.

## Required runtime tests

- disconnecting the initial subscriber does not cancel the fake runner;
- a second subscriber receives missed records in sequence and then live events;
- reconnect at every event boundary produces no gaps or duplicates;
- a second start for one active conversation is rejected;
- Stop before `turn_scope()` is observed;
- the manager never synthesizes domain error or terminal events;
- runner-owned error and `turn_end` events are not duplicated;
- completed runs are removed from manager lookup immediately;
- manager cleanup requests graceful stop, then cancels after its deadline.

All six slices are implemented. HTTP responses are subscriptions to a
process-owned run, `server/message_handler.py` is gone, and conversation resume
returns active-run discovery plus its persisted-snapshot cursor. The browser
tracks processed sequences, retries active-run GETs without resending the user
message, and recovers a completion/pruning race from durable conversation
state. Browser E2E coverage exercises refresh, offline/online recovery, the
completion race, and explicit Stop behavior.
