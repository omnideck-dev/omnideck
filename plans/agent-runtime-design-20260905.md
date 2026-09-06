# Proposed agent runtime and execution design

This proposal builds on the review of upstream commit 6d02b60d. It focuses on execution structure. The six reproduced defects remain a separate backlog; the design assigns their future fixes to clear owners.

Keep two layers in the same repository:

- **sdk:** executes a configured agent using supplied capabilities, history, provider, control, and an event sink.
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

1. Ask AgentFactory to prepare the profile, provider, Agent, AgentCapabilities, and prompt inputs.
2. Obtain the appropriate history view from the session: accumulated root conversation or isolated child view.
3. Establish attribution using the already allocated execution identity.
4. Open execution-scoped resources, including browser preparation.
5. Compose the system prompt and hooks and create ContextManager for this history and these capabilities.
6. Record the invocation input and call AgentExecutor with explicit dependencies.
7. Translate expected execution outcomes, persist permitted skill changes, emit agent lifecycle completion, and release execution resources.

Both root and child calls use this sequence. Differences are explicit policies for history, skill restoration, memory, and resource lifetime. They must not be inferred from HTTP or routine caller types.

A small async context manager and AsyncExitStack can implement resource setup/teardown inside the runner. A separate class for every browser or observer action is unnecessary.

AgentRunner no longer owns the network response, cron scheduling, root conversation reservation, or a second event subscription tree.

**4. AgentFactory — consolidate profile and capability composition**

Extract profile-based preparation from build_agent, build_agent_capabilities, and the duplicated setup in the three callers.

It resolves and validates AgentProfile, translates its model options to a generic Agent, resolves the provider through application configuration, builds AgentCapabilities from base tools/capabilities/skills, restores the permitted persisted skill delta, and prepares prompt inputs such as memory.

Return a small PreparedAgent dataclass, not a running task:

```python
@dataclass
class PreparedAgent:
    agent: Agent
    provider: Provider
    capabilities: AgentCapabilities
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
        agent: Agent,
        capabilities: AgentCapabilities,
        history: ConversationHistory,
        provider: Provider,
        context: ExecutionContext,
        hooks: Sequence[ExecutionHook],
    ) -> ExecutionResult: ...
```

It owns the model/tool iteration, model request construction, tool dispatch, hook ordering, and normalized execution outcome. AgentRunner owns application setup and agent lifecycle; AgentRuntime owns the run and task tree.

The executor uses the supplied provider and execution options instead of loading application config. The active tools come from AgentCapabilities, eliminating the competing Agent.tools list. Required capabilities are explicit; ContextVars remain convenience access for tool functions, bound to the supplied context.

Start with the existing tool helper functions inside this implementation. Extract a ToolExecutor when dispatch policy has enough behavior to justify it; adding an empty wrapper immediately would not improve the design.

Migrate run_turn callers directly to AgentExecutor and remove the replaced entry point in the same change where practical. Do not introduce a compatibility wrapper by default. The SDK execution surface should operate without importing application storage or performing implicit global setup.

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

- Agent retains the existing name and moves from agents.types into the SDK. It holds instructions, model settings, context settings, and execution limits. Provider objects are injected separately; AgentCapabilities owns effective tools.
- AgentCapabilities renames the existing AgentState. It is a per-execution mutable object owning available tools, capabilities, loaded skills, and their prompt guidance. Its app-specific construction and persistence functions move to the factory/composition layer. AgentProfile remains the saved configuration used to prepare Agent and AgentCapabilities.
- ExecutionContext carries opaque run/execution/conversation identity, parent identity, a scoped control object, and an event publisher. It has no HTTP request, websocket, Telegram client, or TaskStore. Each child receives its own context and AgentCapabilities.
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

1. Retain Agent, rename AgentState to AgentCapabilities, and establish the identity and request/result/context contracts. Make the loop accept explicit capabilities/provider/control and extract AgentExecutor. Update affected imports and callers directly.
2. Extract AgentFactory and AgentRunner's shared execution path; migrate spawn_agent onto registered child invocation.
3. Evolve ActiveRunManager/_ActiveRun into AgentRuntime/RunSession and return RunHandle. Keep the existing HTTP endpoints and event payload compatibility.
4. Inject AgentRuntime into TaskExecutor and remove routine-specific execution setup.
5. Enforce the SDK-to-application import boundary and verify that obsolete entry points and duplicate execution paths have been removed.

Acceptance should demonstrate the same profile preparation and lifecycle path for root, child, and routine execution; isolated child histories; a single root terminal event; typed completion without parsing event text; and a headless caller using the runtime without constructing an aiohttp request. Deferred defect fixes can then target these owners without being bundled into every extraction.


**Migration discipline and regression coverage**

Each refactor stage updates its affected callers and removes replaced code together. Avoid old-name aliases, dual APIs, and layers of backward-compatible shims. If a temporary adapter is necessary for a concrete caller that cannot migrate in the same stage, document that caller and the removal step; an adapter is an exception, not the default migration strategy. Preserve user-visible behavior and persisted data contracts intentionally.

Add or strengthen integration and E2E tests alongside each behavioral change. Reuse existing coverage where it already proves the contract; do not add tests that merely check class names or duplicate the implementation.

- SDK extraction: integration tests exercise actual provider requests, tool execution, capability/skill changes and prompt guidance, stop/nudge handling, and typed completion through FakeProvider. Run relevant chat/tool/skill E2E scenarios through the real application.
- Shared runner and child invocation: integration tests verify common profile preparation, child history and capability isolation, attribution, and child failure/stop behavior. E2E tests drive real delegation through FakeProvider and check its visible output and lifecycle.
- Runtime/session ownership: integration tests verify conversation admission, observer detachment, replay, owned task cleanup, and exactly one terminal event. E2E tests cover disconnect/reconnect, stop, nudge, and restored conversation behavior.
- Routine migration: integration tests verify TaskExecutor uses the ordinary runtime, maps completion correctly, and propagates explicit cancellation. E2E tests start routines through the application and verify persisted results and their presentation.

Integration and E2E execution coverage uses the actual FakeProvider protocol with the real runtime; scripted model responses are the controlled boundary. Do not intercept chat responses or seed fabricated JSONL to stand in for execution. Assert observable outcomes, persisted state, and event ordering where relevant. Run the full integration suite and relevant E2E scenarios manually before each refactor PR, with the complete E2E suite at the final migration boundary; retain the full post-merge E2E release gate.


**First implementation stage**

The SDK extraction retains Agent in sdk.agent and renames the capabilities module and its callers directly. AgentExecutor.execute accepts AgentCapabilities, Provider, ExecutionContext, hooks, and max_parallel_tools; the application resolves provider and concurrency settings. ExecutionControl supplies the shared stop signal and each execution's nudge inbox. ExecutionResult returns success/stopped/error, final or partial output, finish reason, execution-local usage, and error details. Callers that require success use raise_for_status so existing agent lifecycle and task-failure handling remain consistent.

The manager passes its admitted run ID through AgentRunRequest; child executors inherit that ID. Direct root callers and routine task executions allocate their own run IDs. Current turn/agent scopes still own lifecycle events and resource cleanup. AgentFactory, the unified runner setup, and AgentRuntime/RunSession ownership remain the following stages. No run_turn wrapper or AgentState alias is retained.


**Second implementation stage**

AgentFactory now translates profiles into PreparedAgent (Agent, Provider,
AgentCapabilities, and the base system prompt). Application tool selection,
browser capability grants, skill restoration/persistence, and memory composition
have moved out of sdk.agent_capabilities. AgentProfile remains the saved model in
agents; the old agents.build_agent function and SDK spawn implementation are removed.

AgentRunner.execute owns one preparation/execution path for interactive roots,
children, and routine tasks. It allocates an execution ID before preparation and
keeps a live execution registry. Each installed spawn_agent closure binds that
identity; invoking it from another execution or after its owner completes is
rejected. Children get their own filtered history, capabilities, and nudge inbox,
while retaining their parent's run ID, event destination, and stop signal. Spawn
correlation is emitted only after successful preparation. The runner removes
registry entries and child history subscriptions on every exit.

Interactive roots opt into persisted skills and memory. Children and routine
tasks do not. TaskExecutor now calls this shared method while retaining routine
instruction construction, event-log/file collection, turn scope, and conversation
cleanup. This brings routine preparation forward from stage four because routine
agents also need a correctly bound spawn tool. Scheduling, run admission, replay,
and session ownership remain for the AgentRuntime/RunSession stages.

Execution IDs retain their existing dotted format, now allocated before
preparation by the application and passed to agent_span. The conversation catalog
still infers root depth from this format; changing it requires a separate reader
migration. Parent relationships also remain explicit event fields.
Routine lifecycle now includes the profile name, and its context-usage metadata
reports the profile's compaction threshold consistently with chat and child
execution. These are consequences of sharing setup; persisted event shapes and
model-facing spawn arguments remain unchanged.

Regression coverage includes cross-entry FakeProvider execution, nested ownership
and tool-result attribution, memory/history isolation, refusal of stale or
foreign spawn tools, and cleanup after failed/cancelled preparation. The routine
E2E scenario now also runs browser/file work through two child levels, checks the
runtime-generated hierarchy and persisted file result, and opens the result in
the UI. Existing lifecycle, stop, nudge, parallel-child, compaction, skill,
reconnect, and conversation-resume tests continue to cover the shared path.


**Final implementation stage**

Stages three through five are implemented together. `AgentRuntime` replaces
`ActiveRunManager`; `RunSession` replaces `_ActiveRun` and owns all root/child
execution contexts, controls, event replay, conversation leases, disk observers,
artifacts, and cleanup. `RunHandle` is the observer/control API. `RunResult`
contains typed root completion, aggregate execution usage, artifact payloads,
and per-execution results. Admission and task ownership no longer live in SDK
scopes or global nudge maps. Existing handles retain replay after completion;
the runtime drops completed runs from its active maps.

`AgentRunner` retains profile preparation and the common root/child execution
path, but its execution registry and resource setup move into the supplied
session. Parent-bound spawn invocations register children with that session.
`RunPolicy` makes memory, skill restore/persistence, naming, and conversation
lifetime explicit. `TaskExecutor` receives the same runtime used by HTTP, starts
a run, and maps its result. It stores `agent_run_id` separately from workflow
identity and cancels/awaits the owned handle when its routine task is cancelled.

The SDK no longer imports application packages. Configured provider and vision
selection move to `providers`, including FakeProvider because its directive
protocol knows application tools/profiles. Persistent skill catalog/resolution/
policy/tools move to `skills`. The generic `Skill` stays in the SDK. Configured
LLM compaction and scratchpad integration move to `agent_runtime`; generic
context management, strategy contracts, provider adapters, and hooks stay in
the SDK. Old imports, global control registries, the transitional execution
context helper, and the compactor alias are removed directly.

Ownership changes intentionally tighten three behaviors: cancelling a waiter
only detaches it; explicit task cancellation reports agent status `stopped`;
and foreign/stale execution IDs are refused for nudges. All entry points now
attach the same artifact/browser/terminal/event observers. The single root
terminal event is emitted after session cleanup. Cached chat resources retain
their conversation lifetime; routine resources are released before task
completion. HTTP endpoints, event payload shapes, persisted conversations, and
model-facing spawn arguments remain compatible. Old task results load with an
absent optional `agent_run_id`.

Regression tests enforce SDK imports both statically and by importing/executing
it with application imports blocked in a fresh process. Actual FakeProvider
integration tests exercise detached waiters, early cancellation, routine-owner
cancellation and resource release, per-run nudge isolation, and child usage/
artifact aggregation. HTTP E2E adds cross-conversation nudge refusal; routine
E2E verifies stored agent-run identity alongside nested browser/file work.

SDK hook inputs now use structural phase protocols (`Hook`); consumers implement
only the phases they need. Dispatch order and synchronous/async phase behavior
remain unchanged.
