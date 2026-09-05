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
