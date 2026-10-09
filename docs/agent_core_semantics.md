# Agent core and runtime semantics

`agent_core` executes supplied agents. The application runtime prepares them and owns
their lifetime. Both interactive chat and routine tasks use this same path.

`agent_core` names the reusable execution layer; `agent_runtime` names the layer
that prepares and owns runs. “SDK” can describe the overall public toolkit,
rather than naming either architectural layer.

## Package boundaries

- `agent_core`: `Agent`, `AgentCapabilities`, `AgentExecutor`, provider contracts and real
  provider adapters, generic `Skill`, context/history, events, controls, and hooks.
  It does not import application packages or read application settings.
  Application callers use the public agent core exports.
- `agent_runtime`: `AgentFactory`, `AgentRunner`, `AgentRuntime`, `RunSession`,
  `RunHandle`, configured LLM compaction, and the scratchpad hook.
- `conversations`: `ConversationStore` owns live histories, leases, and generic
  conversation resource scopes; persistence remains in the same package.
- `browser`: `BrowserRuntime` assigns browser sessions to conversation or
  execution scopes.
- `agents`: saved `AgentProfile` configuration.
- `providers`: configured provider selection, vision selection, and the
  application-aware FakeProvider directive protocol.
- `skills`: stored skill catalog, resolution, policy, and skill management tools.
- `server` and `tasks`: adapters for HTTP and scheduled workflows.

## Agent preparation and execution

`AgentFactory` resolves an `AgentProfile` into `PreparedAgent`: an `Agent` holding
instructions/model settings/limits, an injected `Provider`, `AgentCapabilities`
holding effective tools and loaded-skill guidance, and the base system prompt.

`AgentRunner` prepares each root or child through that factory and calls
`AgentExecutor.execute` with explicit provider, capabilities, history, hooks,
execution context, and tool concurrency. The agent core returns `ExecutionResult` with
status, output, finish reason, execution-local usage, and normalized error.

Hooks implement the phases they need: turn start/end, before/after model, or
before/after tool. Generic defaults live in the agent core. The runner composes the
application scratchpad hook and configured compaction strategy.

## Run ownership

`AgentRuntime.start(request)` reserves a conversation and creates a `RunSession`
and a background task. It returns `RunHandle`. A second concurrent run in the
same conversation is rejected; different conversations may run concurrently.

The session owns the root and live child `ExecutionContext` objects, shared stop
signal, individual nudge inboxes, event replay, disk observers, artifact records,
and cleanup. It acquires a `ConversationScope` from the runtime's injected
`ConversationStore`; the lease prevents cache eviction during execution.
Children share this scope but retain their own isolated working histories.
`RunPolicy` explicitly controls skill restore/persistence, memory, agent naming,
and cached versus run-lifetime conversation resources.

`RunHandle.events(after_seq)` replays and follows sequenced events. `wait()` returns
`RunResult`, aggregating execution usage and emitted artifacts. Cancelling either
observer detaches it; execution continues. `stop()` requests cooperative stop.
`cancel()` explicitly cancels owned work, and callers await completion to ensure
cleanup. Nudge delivery accepts only live execution IDs belonging to this run.

The session emits exactly one root `turn_end` after cleanup. The runtime removes
completed runs from its active maps. Existing handles retain their result and
replay; later HTTP conversation resume reads persisted events.

## Conversation and browser resources

Application setup creates `ConversationStore`, `BrowserRuntime`, and
`AgentRuntime` together. HTTP browser controls use that same browser instance.
A directly constructed `AgentRuntime()` creates its own store and browser runtime;
it does not require HTTP startup or process-global cleanup registration.

`ConversationStore.acquire()` leases a scope containing history and an
`AsyncExitStack`. Cached conversations retain the scope between runs; routine
task conversations close on their final lease release. Eviction, archive,
delete, and runtime shutdown await conversation resource cleanup. The store
has no browser dependency. Resource cleanup failures propagate after the exit
stack attempts its other callbacks.

For each root or child execution, `AgentRunner` opens an execution exit stack
inside `agent_span` and enters `BrowserRuntime.execution()` with both resource
scopes. BrowserRuntime attaches root browser cleanup to the conversation scope
once, and child browser cleanup to the execution scope. Registration precedes
preparation so partial preparation failures also have an owner. Child cleanup
finishes before `agent_completed`; run cleanup finishes before `turn_end`.

Browser tools resolve the explicitly bound browser runtime through an execution
context variable, with no process-global fallback. Nested execution restores
the parent's binding on exit. `agent_core.agent_span` only binds context and
emits lifecycle events; it owns no application cleanup registry.

`AgentRuntime.close()` first stops and awaits runs, then closes retained
conversation scopes, then closes the browser service and its Chromium host.
The server entry point does not independently close browsers ahead of agents.

## Child execution

The application's `spawn_agent` tool is an ordinary supplied agent core callable. Its
closure binds the parent session and context. Invocation verifies that parent is
still live and currently bound, then registers a child in the same session.
The runner follows its ordinary preparation/execution path.

A child gets isolated history, capabilities, and a nudge inbox. It shares the
run ID, stop signal, and canonical event destination. Nested children use the
same rules. Child output becomes the parent's tool result; child status and
usage remain individually available in `RunResult.executions`.

`agent_span(execution=context)` binds the supplied identity and emits agent
start/completion events. Cancellation reports `stopped`. The generic standalone
agent core `turn_scope` remains a context-binding convenience; it owns no application
run registry, remote-control map, persistence, or root terminal event.

## Events and history

`publish_event()` enriches events with the bound execution's identity, name, and
depth. Events flow through the session's history to disk observers, child-history
projections, artifact indexing, and replay. Children create no disk writers.

`ConversationHistory` projects model messages. Each agent's `ContextManager`
controls compaction using an injected `ContextStrategy`. The application's
`LLMCompactionStrategy` owns configured summarization and model resource cleanup.
It keeps assistant messages with their tool results at compaction boundaries.

## Channel and routine adapters

HTTP handlers translate requests, subscribe to a handle, and expose controls.
A future messaging channel can do the same without changing agent core execution.
Channel credentials, message delivery, and retries belong in that adapter.

`TaskRunner` retains workflow scheduling, dependencies, and retry policy.
`TaskExecutor` builds task instructions, starts the injected shared runtime, and
maps its result to persisted task output. `TaskResult.agent_run_id` identifies
that agent run separately from its workflow `run_id`. An explicit routine-owner
cancellation cancels its handle and waits for session cleanup.
