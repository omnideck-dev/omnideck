# Provider usage details

Implemented on `feat/provider-usage-details`, based on current main with the
conversation Details branch merged locally. The parent worktree and PR are
unchanged.

## Data flow

Provider adapter → `ChatResponse.usage` → per-call `IterationPayload.usage` →
agent `usageByIteration` → frontend `aggregateUsage` → expandable agent rows.

- Input includes cached reads and writes for every provider. Anthropic's
  separate counters are combined in its adapter, not in execution or the UI.
- Optional counts and reported USD cost use null for unavailable; zero remains
  a reported value. OpenRouter cost means the account charge, not the separate
  upstream BYOK inference charge or credit-purchase fees.
- The frontend sums root spans across turns and each spawned agent separately.
  It tracks reporting coverage independently for each metric and marks partial
  values. Historical scalar totals still work without an invented breakdown.
- Cache-write counts and Anthropic's 5-minute/1-hour buckets remain in events
  for diagnostics. Normal UI shows only input, cached input, output, and cost.
- The existing SDK execution summary is preserved for SDK consumers; it is not
  the source of conversation/agent UI totals.
- No SDK dependency upgrade is required. Ollama's local response decoder adds
  the documented cached-token field that ollama-python 0.6.1 otherwise drops.
  Other SDK clients/classes are not patched globally.
- Reported cost is currently supplied by OpenRouter. Direct OpenAI, Anthropic,
  and Ollama calls have no cost estimate added by this change.

## Verification

Run `just check`, `npm --prefix server/ui test`, and
`uv run pytest tests/unit/agent_core tests/integration/agent_core tests/integration/agent_runtime`.
Provider tests exercise SDK decoding and streaming completion records without
making billable API calls.

For the component browser review, run Vite on an unused local port 5192:
`npm --prefix server/ui run dev -- --host 127.0.0.1 --port 5192 --strictPort`, then
`uv run python mockups/provider-usage-details/verify.py`.
Screenshots use the actual components with clearly identified sample usage.

## Provider contracts

- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
- [OpenRouter USD-denominated credits](https://openrouter.ai/support)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Ollama usage fields](https://docs.ollama.com/api/usage)
