# Agent execution regression contracts

Run `just integration`. These tests connect the production `ActiveRunManager`,
`AgentRunner`, SDK scopes/hooks/tool loop, subagent execution, `TaskRunner`,
`TaskExecutor`, and file-backed stores. They do not mock `AgentExecutor.execute` or rewrite
history/event behavior. They deliberately live outside the SDK unit suite's
legacy compatibility fixture.

The harness substitutes provider I/O, browser service I/O, tool-category
discovery, and storage locations. Tool functions, profile/skill resolution,
event projection, disk serialization, and lifecycle hooks execute normally.
Tests requiring actual Chrome belong in browser integration or E2E tests.

`ScriptedProvider` accepts typed responses, deltas, errors, and event-gated
async generators. It records model requests so the tests can assert profile
options, active tools, and history isolation. Unexpected model requests fail.
Concurrency tests use events to establish overlap and completion order.

The E2E counterpart uses the existing `MOCK_LLM=1` FakeProvider directive
protocol. See `tests/e2e/api/agent_runs`, `tests/e2e/routines`, and existing
chat/network/browser suites. Keep both levels: HTTP assertions protect the
external contract; these tests inspect internal model inputs and race boundaries
that the directive protocol does not expose.

During the runtime refactor, adapt construction and infrastructure bindings in
the harness to the new composition API. Preserve behavioral assertions rather
than replacing the new shared executor with mocks. Add intended-behavior tests
when implementing new cancellation, budgeting, retry, or run-lifetime policies;
the review probes for existing defects are not acceptance tests.
