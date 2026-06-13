# Future Refactor Ideas

## Move title generation out of message_handler

Title generation currently lives in `_run_turn` in `server/message_handler.py`. It works but isn't the best home for it. The message handler is already doing a lot — managing the turn lifecycle, event buffering, persistence hooks, etc.

A better approach would be to trigger title generation from the persistence layer (`conversations/_store.py`) since that's where the conversation is actually saved. The problem today is that the store is fully synchronous (plain file I/O), so it can't kick off an async LLM call. If the store is ever made async or moved to a database, title generation should move there too.

## Generate proper icon components for Sidebar

The icons in `server/ui/src/components/Sidebar.jsx` are defined as raw SVG path strings inline in the `PANELS` array. This makes them difficult to read, edit, and maintain — you can't tell what an icon looks like without rendering it.

Since we generate our own icons, we should generate proper icon components for each sidebar panel so each entry references a readable component name instead of opaque path data. This would also make it easier to add new panels or swap icons later.

## Remove fake turn_end from message_handler error path

In `handle_user_message`, the `except` block emits a `TurnEndPayload` when something fails before the turn even starts (e.g. agent build failure, queue setup error). This is misleading — no turn actually started, so there's no turn to end. The frontend should handle the connection erroring out on its own instead of relying on a fake `turn_end` event.

## Unify agent spawning

Currently root agents (message_handler), sub-agents (spawn_agent), and background tasks (TaskExecutor) each duplicate agent setup logic — system message construction, context manager creation, hook assembly, skill/tool management, persistence. Each new caller re-implements the same pattern with slight variations.

**Goal:** Extract a shared `run_agent_turn()` that handles all common setup. Callers only differ in how they provide the conversation:
- message_handler: reuses existing ConversationHistory, persists to main history.json
- spawn_agent: fresh ConversationHistory, persists to sub_agents/ dir
- TaskExecutor: fresh ConversationHistory, persists to goals/ dir
- Future wrappers (Telegram bot, CLI): same shared function, different conversation source

**What moves into the shared path:**
- System message construction (base prompt + memory + skill prompts)
- Hook assembly (default_hooks + PersistenceHook)
- ContextManager creation
- LoadedSkills creation and skill pre-loading
- agent_span lifecycle

## Revisit default_hooks assembly

`default_hooks()` in `sdk/hooks/_default.py` builds the hook list via a series of conditionals that check agent options, `max_iterations`, and whether a `ctx_manager` was provided. Every caller gets the same monolithic list with no way to opt out of individual hooks or inject custom ones without bypassing the function entirely.

This makes it hard to customize hook sets for different agent types — for example, a sub-agent might not need `ScratchpadHook` or `LoadedSkillHook`, but there's no way to express that without duplicating the whole assembly. The function also takes `agent: Any` and reaches into `agent.options` directly, coupling it to the agent's internal shape.

A better approach might be a declarative hook configuration (e.g. a list of hook classes/names on the agent definition) or a builder pattern that lets callers include/exclude specific hooks. This would also make it easier to test individual hooks in isolation without standing up the full default set.

## Eliminate integration tests

Server tests (tests/server/) trigger real Ollama HTTP calls during `create_app()` import/startup, even though test logic uses monkeypatched fakes. All tests should run without external services. Audit the app startup path to eliminate the Ollama call.

## Add streaming progress to grounding tool

`tools/_grounding.py` uses a blocking `subprocess.run()` with a 31-minute timeout. When the UI-TARS model (~33 GB) downloads for the first time, the UI goes silent with no progress. Image and music generation both stream JSONL progress events. The grounding tool should do the same.

## Simplify inference client/server communication

Now that inference runs in the same container as the app, the HTTP client/server layer between `inference_client.py` and `inference_server.py` is unnecessary overhead. The server was originally in a separate container, so HTTP was the only option. The separate *process* is still valuable (GPU memory isolation, NF4 weights can't be freed in-process, idle shutdown to reclaim VRAM), but the HTTP layer could be replaced with direct subprocess stdio. The streaming JSONL protocol is already line-based, so the generation tools could spawn the server script directly and read its stdout instead of going through HTTP. This would remove the health check polling, port management, and urllib dependency.

## Slim image variant (no GPU deps)

The full image is ~9 GB, mostly PyTorch + diffusers + ACE-Step. Users who only want chat, browsing, and coding don't need any of that. A `computron_9000:slim` image that skips the GPU layers would be ~3 GB and much faster to pull. Could be a separate Dockerfile stage or a build arg that skips the torch/diffusers/ACE-Step layers.

## Fix thinking-only responses ending sub-agent turns

`run_turn()` in `sdk/turn/_execution.py` ends the turn when the model produces no tool calls (`if not tool_calls: return final_content`). This doesn't distinguish between "agent gave a final answer" and "model emitted only thinking tokens and stopped." When the model produces thinking but no content and no tool calls, the turn returns `None`, and `spawn_agent` returns an empty string to the parent — silently losing all the sub-agent's work.

**Observed:** CODEBASE_ANALYZER sub-agent ran 15 iterations reading files, went through 3 compaction cycles, then on its final iteration the model produced only `Thinking: Now let me read the server files...` with no content or tool calls. Parent got `""` back, tried the scratchpad (empty), then redid all the analysis itself.

**Fix:** The completion signal should be "content with no tool calls", not just "no tool calls":
- Content + no tool calls → done (agent gave its final answer)
- No content + no tool calls + thinking → incomplete; inject a system message ("Continue — provide your response or next tool call") and retry
- Cap retries at 2-3 to prevent infinite loops on a truly stuck model
- After exhausting retries, fall back to using the thinking text as the result

## Clarify run_turn result vs hook payload semantics

`run_turn()` uses a local `final_content` variable for two related but distinct things:
- The successful return value consumed by `TaskExecutor` and `spawn_agent`
- The `on_turn_end(final_content, agent_name)` hook payload passed from the `finally` block

That name is slightly misleading. During a multi-iteration tool loop, it is overwritten with the latest assistant content each time the model responds. It only becomes truly "final" when the response has no tool calls and the turn returns. On a mid-stream stop, the code may assign partial streamed content to `final_content` before re-raising `StopRequestedError`; callers never receive that value, but `finally` still passes it to hooks. Persistence does not read `final_content`; it persists `ConversationHistory`.

This is not currently buggy, but the semantics are overloaded enough to revisit. A cleaner shape would separate:
- `latest_assistant_content` for hook/debug metadata
- an explicit successful `return_content`
- persisted transcript state exclusively in `ConversationHistory`

Also consider whether `on_turn_end` should receive a richer result object (`status`, `content`, `stopped`, `error`) instead of a nullable string. That would avoid overloading content with lifecycle state.

## Split model-facing history from durable UI transcript

`ConversationHistory` currently serves two purposes:
- The provider-facing chat history sent to OpenAI/Ollama/Anthropic adapters
- The persisted transcript used to restore the UI

Mid-stream stops expose the mismatch. If the user stops after visible assistant content has streamed, persisting that partial content as an assistant message is valid: the assistant visibly said those words, and providers can consume the string on the next turn. If the user stops while only thinking/reasoning has streamed, there is no portable provider-facing assistant message:
- OpenAI-compatible chat requires assistant `content` unless the message contains tool calls; `content: None` can fail validation.
- Anthropic treats assistant messages as content blocks and empty/final assistant turns have special prefill semantics.
- Ollama supports a separate `thinking` field, so it can preserve information that other providers cannot represent consistently.

The minimal safe behavior is to persist only stopped partials that include visible `content`. Thinking-only stopped output remains live UI state and the durable lifecycle event is `agent_completed(status="stopped")`. That avoids corrupting provider history, but after reload the thinking-only partial is not visible and the next model call sees consecutive user messages.

A cleaner design would persist a provider-neutral event transcript separately from provider history:
- Store streamed `content`/`thinking` deltas and lifecycle events as UI events.
- Restore the chat UI by replaying persisted events, not by overloading LLM messages.
- Build provider requests from a sanitized model history that excludes UI-only artifacts.
- Optionally inject a model-safe note such as "Previous assistant turn was stopped before producing visible output" when that continuity is useful.

That would let Omnideck preserve the full user-visible stopped-turn experience without sending empty or thinking-only assistant turns to providers.

## Skip model unload for cloud models

`_unload_model()` in `sdk/context/_strategy.py` runs `ollama stop <model>` after every compaction to free VRAM. This fails silently for cloud models (e.g. `kimi-k2.5:cloud`) since they aren't loaded in Ollama. Check for a `:cloud` suffix (or whatever convention distinguishes remote models) and skip the subprocess call.

## Rename context_id to agent_id in agent_span

`agent_span` in `sdk/events/_context.py` yields a value called `context_id` internally, but it's the agent's unique identifier — used as the key in `_agent_browsers`, passed to `release_agent_browser`, returned by `get_current_agent_id()`, and stamped on every `AgentEvent`. The name `context_id` is confusing because `ContextManager` and `BrowserContext` are also "contexts" in this codebase.

Rename `context_id` → `agent_id` throughout `_context.py`, and rename `_context_stack` → `_agent_stack` (it stores `(agent_id, agent_name)` tuples). `_make_child_context_id` → `_make_child_agent_id`. The public API (`get_current_agent_id`) already uses the right name.

## Optimize FLUX model downloads

`_download_model()` in `container/inference_server.py` uses `snapshot_download()` which pulls the entire HuggingFace repo. FLUX repos contain both single-file weights (e.g. `flux1-schnell.safetensors`, ~24 GB) and diffusers-sharded weights (`transformer/`, ~24 GB) — downloading both doubles the size from ~34 GB to ~58 GB per model. Use `allow_patterns` to skip single-file weights, or switch to `from_pretrained()` which only fetches what the pipeline needs.

## Run dbus-launch as the computron user

`container/entrypoint.sh:48` runs `eval $(dbus-launch --sh-syntax)` as root, then exports the resulting `DBUS_SESSION_BUS_ADDRESS` so subsequent `gosu computron` processes (Xfce, AT-SPI clients) connect to a session bus owned by root. It usually works because the daemon's unix socket is in `/tmp` and world-accessible, but session buses are conceptually per-user — flaky AT-SPI behavior or Xfce startup quirks would land here first. Cleaner: launch the bus as the computron user (`gosu computron dbus-launch ...`) and capture the address via temp file.

## Add `set -eu` to entrypoint.sh

`container/entrypoint.sh` runs without `set -e` or `set -u`, so silent failures accumulate. The `chown` ordering bug that broke Chrome would have been louder if errors propagated. The `cp -rn /etc/xdg/xfce4/* ... 2>/dev/null` on line 35 also swallows real failures — drop the `2>/dev/null` so a missing xdg dir surfaces. Skip `-o pipefail` since several lines deliberately use `|| true` and `2>/dev/null` patterns that would conflict.

## Monitor or supervise desktop background services

When `ENABLE_DESKTOP=true`, `container/entrypoint.sh` starts `startxfce4`, `x11vnc -bg`, and `websockify ... &` as fire-and-forget background processes. No PID tracking, no restart on death, no log if they crash. The app loop has restart-on-crash logic; the desktop services don't. If x11vnc dies 30s in, the noVNC bridge silently hangs and the user sees "connecting…" forever. Either capture their PIDs and `wait` on them like the app loop does, or run them under a tiny supervisor (s6-overlay, runit, or a shell loop per service).

## Backoff for app restart loop

`container/entrypoint.sh:96-97` sleeps 2 seconds between app restarts. If `main.py` crashes on import (e.g. bad config, broken migration), the loop respawns it every 2s indefinitely, flooding logs and burning CPU. An exponential backoff capped at ~30s would make crash-loops obvious without the noise — and a max retry count would let the container exit cleanly so an orchestrator could surface the failure.

## Unify the two `entries[]` builders (live reducer vs. resume transform)

The UI represents an assistant turn as an ordered `entries[]` array (thinking / content / tool_call / file_output). It is built two different ways that converge on the same shape:

- **Live** — streaming events flow into the `useAgentState` reducer, which accumulates each agent's `activityLog` and merges consecutive same-type deltas.
- **Resume** — `_historyToMessages` in `useStreamingChat.js` converts a loaded conversation's raw LLM messages into the same `entries[]`, including merging a turn's tool-call round-trips into one message.

This is a duplicated *contract*, not duplicated code — the two can't share a function because one is an incremental reducer and the other a batch transform. The risk is drift: the entry types, ordering, and merge rule must stay in sync across both.

**Goal:** make the reducer the single `entries[]` builder. On resume, replay the loaded history as synthetic reducer actions (`AGENT_STARTED`, `APPEND_STREAM_CHUNK`, `APPEND_ACTIVITY`) instead of transforming to `entries[]` directly. The resume side then shrinks to a thin "raw message → which actions" mapper.

**Why it's non-trivial:** the reducer was built for the live flow. Bulk-replaying a whole conversation pokes at behavior it doesn't expect — multiple historical root agents (each past turn is its own root), `AGENT_STARTED` side effects (preview carryover, `networkActivated`, `selectedAgentId`), synthetic agent ids/timestamps, and tool-call arg shapes. `setMessages` is still needed for user messages and the assistant stubs that carry `agentId`. It needs its own testing pass — medium effort, real edge-case risk. Own commit/PR, not a fold-in.

Until then `_historyToMessages` stays — small, pure, tested.

## Replace the hand-rolled tool type→schema layer in sdk/tools

`sdk/tools` hand-rolls type-driven conversion in two independent places that
share no code and have already drifted:

- `_coerce_value` in `_helpers.py` — inbound: validate/coerce LLM arg JSON
  against a tool's signature before the call.
- `_python_type_to_json_schema` in `_callable_schema.py` — outbound: build the
  OpenAI/Anthropic tool schema from the signature.

Both re-implement "walk a Python annotation, branch on `list` / `Union` /
Pydantic / scalar." The drift is not hypothetical — measured against the real
provider SDKs, the hand-rolled outbound converter silently degrades any param
the `_TYPE_MAP` doesn't cover:

- `Literal["a","b"]` → emitted as a bare `{"type": "string"}`; the `enum` is
  lost, so the model is never told the allowed values.
- a Pydantic-model parameter → emitted as `{"type": "string"}`; the nested
  object schema is lost entirely. Inbound, the *same* param is validated as the
  model — so the model is told "send a string" while the coercer demands a
  structured object. Guaranteed mismatch.
- `dict[str, V]` → `{"type": "object"}` with the value type dropped.

The inbound side mirrors the gaps: `Literal` values aren't validated
(out-of-enum passes through), `dict` values aren't coerced, multi-member unions
pass through unchecked, and `int <- 3.9` silently truncates.

## Two viable directions

**Direction 1 — shell out to each provider's own generator. Rejected.**
Investigated against the installed SDKs; it does not hold up:

- The **OpenAI** base SDK has no callable→schema entry point at all. Its
  `pydantic_function_tool` takes a Pydantic *model*, not a function; raw-callable
  support lives only in the separate Agents SDK.
- **Anthropic**'s `@beta_tool` is real and docstring-aware but **beta**, and
  requires decorating every tool.
- **Ollama**'s converter is a private `_utils` import and *crashes* on natural
  signatures: under `from __future__ import annotations` (which the tool modules
  use), a `Literal[...]` or `Optional[...]` parameter raises
  `PydanticUserError: not fully defined`, because it builds a synthetic model
  from the stringized annotations without resolving forward refs (no
  `eval_str`). Latent today only because every `Literal`/`Optional` currently
  lives *inside* a Pydantic model, which resolves fine — the first tool that
  takes `mode: Literal["fast","slow"]` as a direct param breaks Ollama at
  runtime while the others keep working.
- Fatal flaw even if those were fixed: three generators produce three
  *different* schemas for the same tool (titles, `$defs`, `additionalProperties`,
  `anyOf` shape all differ). That is the opposite of provider-agnostic, and it
  surrenders control of the exact bytes sent to the weaker OpenRouter models
  where `anyOf` adherence is already shaky.

**Direction 2 — one Pydantic model per tool, fed to every provider. Chosen.**
The sharper framing than "share a walker": generate one schema *ourselves* and
send that same dict to **every** provider, Ollama included. Ollama's
`chat(tools=...)` accepts pre-built tool dicts, not only callables, so we stop
handing it raw callables and the hidden third converter disappears.

Both seams are already JSON — a schema dict in, an args dict out (every provider
normalizes its wire tool-call back to a Python dict before it reaches the turn
loop). One Pydantic model sits exactly at both:

- Build one model per tool from the signature (`create_model` over the params,
  `eval_str=True` for PEP 563, docstring `Args:` → `Field(description=...)`).
- **Outbound:** `model.model_json_schema()` → post-process to the shared
  OpenAI/Anthropic shape (strip `title`, decide on `$defs` inlining and
  `additionalProperties: false`). One schema, sent to all four providers.
- **Inbound:** `model.model_validate(args)` replaces `_coerce_value`. `Literal`,
  nested models, `dict[str, V]`, and unions all get validated for free, by the
  same definition that produced the schema.

This deletes `_python_type_to_json_schema`, most of `_coerce_value`, and the
Ollama raw-callable special-case in one move. It is the structural follow-up to
the inbound strictness fix (bare string vs. `list[str]`); that fix made coercion
fail loudly but left both walkers in place.

**Carry-overs that must survive the swap** (these are the regression risks):

- The existing **strict** behavior — a bare string where `list[str]` is
  annotated must still raise. Pydantic in lax mode is *more* permissive than the
  current coercer (`"7" -> 7`, `3.9 -> 3`), which would trade loud failures for
  silent ones — forbidden by the testing conventions. Run the model strict-ish
  and add back only the LLM-reality coercions that are genuinely wanted (the
  `"true"/"yes"/"1"` bool strings).
- The **loud, per-parameter error messages** the turn loop surfaces to the model
  on a bad call (`Invalid value for parameter 'x' of tool 'y': ...`). Pydantic's
  `ValidationError` must be reshaped into that, not leaked raw.
- `estimate_tool_tokens` rides on the outbound schema and must keep working.

## Test strategy

The whole point is collapsing three converters into one *without changing any
tool's observed behavior*, so this is test-led. Three layers:

1. **`sdk/tools` units (the model builder).** Extend
   `tests/unit/sdk/tools/test_callable_schema.py` and `test_helpers_prepare.py`.
   Parametrize one matrix of annotation shapes and assert *both* directions off
   the single model: scalars, `list[T]`, `dict[str, V]`, `Optional[T]`,
   `T | None`, multi-member unions (`list[str] | str`), `Literal`, nested
   Pydantic, list-of-Pydantic, self-referencing models, unannotated, `Any`.
   Several current cases encode the *old buggy* behavior and must be **flipped**,
   not kept: `test_unknown_type_defaults_to_string`,
   `test_list_or_str_union_passthrough`, `test_complex_param_types`, and the
   `Literal`/`dict`-value cases. Add the strictness regressions explicitly
   (bare-string-for-list raises; `Literal` out-of-enum raises; named-parameter
   error message shape).

2. **Per-provider input conversion.** One test per provider asserting the tool
   *advertised* to the model is correct for that provider's required shape —
   OpenAI `{"type":"function","function":{...}}`, Anthropic
   `{"name","description","input_schema"}`, Ollama gets the **same dict** (proving
   the raw-callable path is gone). Same input tool, three provider-shaped
   outputs from one schema. Pin a `Literal`/nested-model tool here so the
   previously-dropped `enum`/object structure is asserted present for every
   provider.

3. **Per-provider output normalization.** Already partially covered
   (`test_openai.py::test_tool_call_arguments_serialized_to_json_string`,
   `test_ollama.py::test_tool_calls`, etc.). Fill the matrix so each provider has
   a test that its wire tool-call (OpenAI/Responses JSON **string**, Anthropic
   **dict**, Ollama **dict**) normalizes to the identical
   `ToolCall(function=ToolCallFunction(name, arguments=dict))`, including the
   malformed-arguments fallback path.

A useful backstop for layers 2–3: a single round-trip test per provider through
the `_fake` provider — build schema from a tool, hand a canned tool-call back,
assert it executes — so the input and output halves are exercised end to end
against the one model.

