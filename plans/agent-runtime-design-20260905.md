# Proposed agent runtime and execution design

This proposal builds on the review of upstream commit 6d02b60d. It focuses on execution structure. The six reproduced defects remain a separate backlog; the design assigns their future fixes to clear owners.

Keep two layers in the same repository:

- **sdk:** executes a configured agent using supplied state, history, provider, tools, control, and an event sink.
- **agent_runtime:** owns application runs and composes profiles, conversation persistence, capabilities, resources, and execution.
- HTTP, routines, and future channel adapters depend on agent_runtime. Application wiring depends on the SDK. The SDK core must not import application profiles, browser runtime, conversation storage, or global application settings.

A runtime may be independent of Telegram and HTTP while still knowing about OmniDeck's profiles and conversation store. That is the useful boundary here; a separately distributed SDK package is not required for this work.

**The identities**

| Concept | Meaning | Lifetime |
| --- | --- | --- |
| AgentProfile | Saved application configuration selected by the user | Across runs |
| Conversation | Persistent exchange and its recorded history | Across runs |
| AgentRun | One accepted input and the tree of work it starts | Until that work settles |
| AgentExecution | One root or child agent invocation within a run | One model/tool loop |
| RoutineRun | One workflow execution containing task results | Across multiple agent runs |

A child has a new execution_id, the same run_id, and a parent_execution_id. A routine task starts an ordinary root agent run. Its workflow_run_id remains separate. Existing agent_id event fields can represent execution_id during migration without changing the UI event format immediately.

**1. AgentRuntime — evolve ActiveRunManager**

This is the process-scoped application API. Evolve the existing manager rather than placing a second manager above it.

Responsibilities: accept a run, reserve its conversation, allocate the root run/execution identities, own its background tasks, register children, route stop/nudge requests, expose observation and completion, and coordinate shutdown.

Suggested public surface:

```python
class AgentRuntime:
    async def start(self, request: AgentRunRequest) -> RunHandle: ...
    def get(self, run_id: str) -> RunHandle | None: ...
    def active_for_conversation(self, conversation_id: str) -> RunHandle | None: ...
    async def close(self) -> None: ...
```

An internal invoke_child(parent_execution, invocation) method registers a child and invokes the same AgentRunner used for the root. Initially it is awaited and returns ExecutionResult. It bypasses root conversation admission: acquiring the parent's conversation reservation again would deadlock or reject valid delegation.

The runtime owns task lifetimes. Closing an event subscription or abandoning a wait only detaches that observer. Root completion is published after all work owned by the run has settled. Recoverable child failure can be returned to the parent as a tool outcome; it does not automatically force the root's final result to fail.

**2. RunSession — evolve _ActiveRun into the per-run owner**

The current _ActiveRun already holds replay records, waiters, stop state, and a task. Extend that internal object into a resource scope shared by the root and its children.

It owns the run's control state, execution registry, root conversation/history reference, event sequencing, observer subscriptions, replay buffer, artifact collection, and final result. It attaches EventsLogWriter, BrowserTabsWriter, TerminalWriter, and ArtifactsIndexWriter once per run. Children publish through the same session.

RunSession is an async context manager. Entry attaches observers and establishes the root scope. Exit settles owned work, flushes observers, and releases run resources. It owns the single run terminal event; turn_end remains the existing transport representation during migration. Per-agent lifecycle remains the runner's responsibility.

Conversation lifetime is separate. Closing a RunSession detaches its subscriptions; it does not necessarily destroy a cached interactive conversation or its browser resources. Routine task conversations can release their resources on completion through an explicit lifetime policy.

Keep the initial implementation backed by the existing cache and JSONL writers. This object is the boundary for later durable run records and bounded replay; neither a database migration nor a queue service is a prerequisite.

**3. AgentRunner — one application execution path**

Keep AgentRunner, but make it execute one agent invocation consistently for roots and children. It orchestrates application setup around the SDK executor.

Its sequence is:

1. Ask AgentFactory to prepare the profile, provider, agent specification, state, and prompt inputs.
2. Obtain the appropriate history view from the session: accumulated root conversation or isolated child view.
3. Establish attribution using the already allocated execution identity.
4. Open execution-scoped resources, including browser preparation.
5. Compose the system prompt and hooks and create ContextManager for this history/state.
6. Record the invocation input and call AgentExecutor with explicit dependencies.
7. Translate expected execution outcomes, persist permitted state changes, emit agent lifecycle completion, and release execution resources.

Both root and child calls use this sequence. Differences are explicit policies for history, skill restoration, memory, and resource lifetime. They must not be inferred from HTTP or routine caller types.

A small async context manager and AsyncExitStack can implement resource setup/teardown inside the runner. A separate class for every browser or observer action is unnecessary.

AgentRunner no longer owns the network response, cron scheduling, root conversation reservation, or a second event subscription tree.

**4. AgentFactory — consolidate profile and capability composition**

Extract profile-based preparation from build_agent, build_agent_state, and the duplicated setup in the three callers.

It resolves and validates AgentProfile, translates its model options to a generic AgentSpec, resolves the provider through application configuration, builds AgentState from base tools/capabilities/skills, restores the permitted persisted skill delta, and prepares prompt inputs such as memory.

Return a small PreparedAgent dataclass, not a running task:

```python
@dataclass
class PreparedAgent:
    spec: AgentSpec
    provider: Provider
    state: AgentState
    # Application metadata/prompt inputs needed by AgentRunner.
```

The factory receives a bound child-invocation callable when it installs the spawn tool. That callable captures the actual execution identity; model arguments cannot invent the parent relationship.

AgentProfile stays in agents because it is a persisted application concept. Generic Skill and AgentCapability data can remain in the SDK; application skill lookup and tool selection move into composition.

**5. AgentExecutor — extract the SDK's run_turn engine**

Promote the execution logic in sdk/turn/_execution.py into a reusable executor with an explicit contract. Its local loop variables remain local to execute(), so an executor can be used concurrently without sharing mutable agent state.

```python
class AgentExecutor:
    async def execute(
        self, *,
        spec: AgentSpec,
        state: AgentState,
        history: ConversationHistory,
        provider: Provider,
        context: ExecutionContext,
        hooks: Sequence[ExecutionHook],
    ) -> ExecutionResult: ...
```

It owns the model/tool iteration, model request construction, tool dispatch, hook ordering, and normalized execution outcome. AgentRunner owns application setup and agent lifecycle; AgentRuntime owns the run and task tree.

The executor uses the supplied provider and execution options instead of loading application config. The active tools come from AgentState, eliminating the competing Agent.tools list. Required state is explicit; ContextVars remain convenience access for legacy tool functions, bound to the supplied context.

Start with the existing tool helper functions inside this implementation. Extract a ToolExecutor when dispatch policy has enough behavior to justify it; adding an empty wrapper immediately would not improve the design.

run_turn can temporarily delegate to this executor while callers migrate. The target SDK execution surface should operate without importing application storage or performing implicit global setup.

**6. RunHandle — a view and control surface**

Return a RunHandle from start rather than only a snapshot. It is a lightweight reference to runtime-owned work:

```python
class RunHandle:
    run_id: str
    conversation_id: str

    def events(self, after_seq: int = 0) -> AsyncIterator[SequencedEvent]: ...
    async def wait(self) -> RunResult: ...
    def snapshot(self) -> RunSnapshot: ...
    def stop(self) -> None: ...
    def nudge(self, message: str, *, execution_id: str | None = None) -> None: ...
```

A handle owns neither the run nor a channel. Multiple handles/subscribers can observe the same run. wait observes completion; it must not transfer task ownership to the waiting caller. Child handles can be introduced later if asynchronous delegation becomes a product requirement.

**Supporting types and changes to existing SDK classes**

- AgentSpec replaces/moves agents.types.Agent into the SDK as an immutable execution configuration: name, instructions, model/options, context settings, and execution limits. Provider objects are injected separately; AgentState owns effective tools.
- AgentState remains a per-execution mutable object for tools, capabilities, and loaded skills. Its app-specific construction and persistence functions move to the factory/composition layer.
- ExecutionContext carries opaque run/execution/conversation identity, parent identity, a scoped control object, and an event publisher. It has no HTTP request, websocket, Telegram client, or TaskStore. Each child receives its own context and state.
- ExecutionControl provides stop observation and per-execution nudge delivery. Runtime sessions own the actual control state, including the parent/child relationships. SDK primitives consume it instead of consulting process-global active-run maps.
- ExecutionResult contains status, final/partial output, normalized error, finish reason, and execution-local usage. RunResult adds run identity and aggregates artifact references and usage across the tree without double counting child work. Generic faults that have not been normalized still propagate to the runtime boundary.
- ConversationHistory remains the model-history projection; ContextManager remains the per-agent compaction controller. Their dependencies are injected. RunSession assembles persistence and observation around them.
- Hooks get typed lifecycle contracts. Generic hooks remain in the SDK; application hooks and app-specific defaults are composed by AgentRunner.
- agent_span accepts the runtime-allocated identity and remains a useful attribution/lifecycle helper. turn_scope sheds process-wide admission, active-run bookkeeping, and terminal ownership into AgentRuntime/RunSession. Its remaining context binding can be a small internal SDK helper.
- publish_event remains available to tools as a convenience over the scoped event publisher. There is one canonical event path; a child does not create separate disk writers.

**How callers interact**

Interactive input:

```python
handle = await runtime.start(AgentRunRequest(
    conversation_id=conversation_id,
    profile_id=profile_id,
    message=text,
    attachments=attachments,
))
async for event in handle.events():
    await send_to_http_client(event)
```

A future channel adapter maps its channel/thread identifiers to a conversation_id, translates input/attachments, starts the run, and renders selected events or the final result. Editing messages, batching deltas, delivery retries, and channel credentials belong to that adapter. No Channel base class or channel-specific runtime fields are needed now.

Sub-agent input:

The model calls the existing spawn_agent tool shape. Its bound application implementation asks AgentRuntime to invoke a child under the current execution. The runtime registers it; AgentRunner performs the same preparation and calls the same AgentExecutor. Child history is isolated while events and root control are shared. The tool returns the child output in its current model-facing format.

Move the app-aware spawn implementation out of sdk/tools/_spawn_agent.py. The SDK executes the tool as an ordinary supplied callable and does not import the runtime to accomplish delegation.

Routine input:

TaskRunner retains cron evaluation, dependency readiness, concurrency policy, and task retry scheduling. TaskExecutor retains instruction construction and mapping RunResult back to TaskResult. It starts a run and awaits its handle, removing its independent browser/hook/history/lifecycle assembly. Record agent_run_id on TaskResult to connect workflow results to inspectable runtime work.

When the routine owner explicitly cancels a task, its adapter requests stop on the run handle. This is an ownership action distinct from a passive subscriber disconnect.

**A practical migration**

1. Establish the identity and request/result/context contracts, then make the current loop accept explicit state/provider/control. Keep existing public paths available during transition.
2. Extract AgentFactory and AgentRunner's shared execution path; migrate spawn_agent onto registered child invocation.
3. Evolve ActiveRunManager/_ActiveRun into AgentRuntime/RunSession and return RunHandle. Keep the existing HTTP endpoints and event payload compatibility.
4. Inject AgentRuntime into TaskExecutor and remove routine-specific execution setup.
5. Remove the compatibility entry points and enforce the SDK-to-application import boundary.

Acceptance should demonstrate the same profile preparation and lifecycle path for root, child, and routine execution; isolated child histories; a single root terminal event; typed completion without parsing event text; and a headless caller using the runtime without constructing an aiohttp request. Deferred defect fixes can then target these owners without being bundled into every extraction.
