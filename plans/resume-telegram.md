# Resume — Telegram integration PR

Where to pick up next session.

## PR

- **omnideck-dev/omnideck#4** — `feature/telegram-integration-v2` → `main`
- Built originally on `lefoulkrod/computron_9000#55` (closed/abandoned once
  the repo moved to the `omnideck` origin); branch history shows the full
  trail of incremental commits.

## Branch state

- Synced with `origin/main` via merge `e15355f` (resolved 5 conflicts in
  the integrations area where the new HTTP/`call_api` integration overlapped
  with our Telegram additions — both kept, no behavior lost).
- 1429 unit tests pass.

## What's landed on this branch

1. **Telegram channel** (`channels/telegram/_channel.py`) — pulls updates
   from the broker via `next_updates`, dispatches per-chat turns, renders
   status messages (`🤔 Thinking…` → tool labels → `✍️ Writing…`), sends
   replies as MarkdownV2 (via `telegramify-markdown`), handles inbound
   photos + documents, `/list` (search and resume any conversation),
   `/profile` (inline-keyboard picker).
2. **Credential-isolated broker** (`integrations/brokers/telegram_broker/`)
   — bot token stays in the broker subprocess, never enters the main app.
   Verbs: `get_me`, `next_updates`, `send_message`, `send_document`,
   `send_chat_action`, `answer_callback_query`, `edit_message_text`,
   `delete_message`.
3. **`ConversationCache`** (`conversations/_cache.py`) — bounded-LRU
   hydrate/evict, shared between the web/SSE handler and the Telegram
   channel; skips eviction of conversations with an in-flight turn.
4. **`TurnExecutor` refactor** (slimmed) — `Conversation` now holds
   `agent_state`; the executor stops loading skills / saving events /
   firing first-turn hooks. Channels do that wiring inline. Covers the
   web handler, Telegram channel, `TaskExecutor`, and `spawn_agent`.
   `TurnPersistence` Protocol moved to `sdk/turn/_persistence.py`.
   `SystemPromptBuilder` dropped.
5. **Goal-run notifier settings** — env vars
   `TELEGRAM_INTEGRATION_ID` / `TELEGRAM_CHAT_ID` retired. Now in
   `settings.json` as `telegram_notifier_integration_id` /
   `telegram_notifier_chat_id`, editable in **Settings → System →
   Notifications**. Migration 006 seeds empty defaults on existing installs.
6. **Three earlier PR-review fixes** (formatter, channel rename,
   env→settings) — see commits `a93ab3b`, `d0364ae` and the resolved
   threads on the original computron PR for context.

## Known / deferred follow-ups

- **No streaming reply for Telegram.** We buffer the full agent reply
  and send it in chunks at turn end (via `to_markdownv2_chunks`).
  Real-time streaming would need either per-paragraph `send_message`
  calls or `edit_message_text` to grow a single message — both have
  Telegram rate-limit and chunk-boundary concerns. Not a blocker.
- **Parallel sub-agent browser contention** — when an agent spawns
  sub-agents in parallel, browser tool calls still serialize. Needs
  per-agent browser contexts. Tracked separately
  ([[project_parallel_subagents]]).
- **Title generation on first turn is fire-and-forget** — if the title
  model is slow or unhealthy, the user just sees the conversation ID
  on `/list` until it lands. Acceptable.
- **No live chat-ID discovery** in the notifier setup — user has to
  copy chat.id from `getUpdates` JSON. We discussed a broker-side
  "recent chats" registry to power a dropdown; deferred until someone
  trips over the manual flow.
- **`telegramify-markdown` corner cases** — if the agent emits
  malformed markdown (unbalanced backticks across chunk boundaries,
  weird nested formatting), the Telegram API may reject. Today we
  log+warn on send failures and the user just sees nothing for that
  chunk. Worth watching once real traffic hits.

## How to pick up next session

1. `cd ~/repos/computron_9000-telegram && git status` — confirm branch
   `feature/telegram-integration-v2`, clean tree.
2. `gh pr view 4 --repo omnideck-dev/omnideck` — check for new review
   comments and CI status.
3. If new inline review comments: `gh api repos/omnideck-dev/omnideck/pulls/4/comments`
   to fetch, then walk them one at a time (same pattern as the three
   from the computron PR).
4. For manual smoke testing: `just dev` brings up the container; add a
   Telegram integration via the wizard; talk to the bot; verify
   MarkdownV2 rendering + status indicator + `/list` resume work.
5. The dev container is `computron_virtual_computer` under **docker**,
   not podman.
