# Agent execution E2E

Run against a disposable application container with the real server, agent
runner, SDK loop, tools, persistence, and scheduler. `just e2e` sets `MOCK_LLM=1`
inside that container to select the existing in-process `FakeProvider`.

```sh
just e2e tests/e2e/ --browser-channel chrome
```

To avoid collisions with another local run, set `E2E_CONTAINER` and `E2E_PORT`.
`E2E_IMAGE` selects an image; use `E2E_SKIP_BUILD=1` only when that image already
contains the source being tested.

Playwright artifacts go in `test-results/playwright/`, which pytest deletes at
session start. Never put manual-container state or persistent fixtures in that
directory. Keep manual state outside test output trees entirely.

## Fixture boundary

- Drive model behavior with `tests.e2e._protocol`: `say`, `bash`, `write_file`,
  `send_file`, `spawn`, `parallel`, and the provider failure/streaming controls.
- Use `model_script` when a model response needs thinking/content before its
  tool requests. Each step uses SDK `ChatMessage` fields. Non-final steps must
  call tools so execution continues. Use it as a complete response sequence;
  it can also be the body of a `spawn` directive.
- Let actual execution produce tool results and all application events.
  Runtime E2E must not fulfill `/api/chat` with fabricated JSONL or write
  conversation event logs. Request observation and network interruption tests
  can intercept traffic while forwarding actual server responses.
- For resume scenarios, create the conversation with `run_turn` or
  `create_conversation` from `tests.e2e._runtime`, then resume it through the UI.
  Prepare titles/pins/folders through public metadata APIs. Delete fixtures
  through the API after the test.
- Trigger real compaction with a small-context temporary profile and configured
  FakeProvider summarizer. Assert a compaction was produced before comparing
  its persisted statistics/summary with the UI. Assert structural behavior
  (agent identity, ordering, scope, continued execution) separately.

For example, this requests a real bash tool invocation between two model replies:

```python
chat.send(model_script(
    {"thinking": "Check the result", "content": "Starting",
     "tool_calls": [model_tool("run_bash_cmd", cmd="printf proof")]},
    {"content": "Finished"},
)).wait_streaming()
```

The fake controls model output; the runtime owns everything after that boundary.
These tests verify execution and UI behavior, not live model answer quality.

## Agent and skill editors

`pages/tool_selection.py` models the shared Add picker and selected rows used by
both editors. Use visible roles and labels for actions, and the selected-row ID
for saved identity. Do not restore the removed category tab or pill selectors.

Coverage includes:

- `profiles/test_simple_editor.py`: save/discard, reload, model settings,
  browser/autonomy controls, and phone/desktop layouts.
- `profiles/test_expandable_selection_rows.py`: shared row alignment, keyboard
  disclosure, independent removal, and tool-label overflow.
- `settings/test_selection_navigation.py`: direct and skill selections,
  searchable picker, exact-account navigation, approval refresh, and draft
  preservation when leaving the skill editor.
- `settings/test_selection_recovery.py`: failed-save retry, catalog outage
  without selection loss, and exports excluding local connection authority.

Selection tests use real application APIs and the local test integration broker.
Failure tests intercept only the request being failed; retries and persistence
still use the real server. The MCP sign-in tests in `settings/test_mcp_integration.py`
use a local OAuth/MCP service in place of the external provider.

Run the entire app suite with `just e2e`; a focused editor pass is not a substitute
for it. Run `just check` after the disposable container has been cleaned up if
its temporary vault is inside the checkout: that vault is deliberately not
readable by the host type checker.
