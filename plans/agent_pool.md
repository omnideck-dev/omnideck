# Resource-Based Agent Pool

## Context

Omnideck runs as a single Python/aiohttp process with no global limit on concurrent agent execution. Today, `AgentRuntime.start()` only enforces one-run-per-conversation — any number of conversations, subagents, and background routines can execute simultaneously, unbounded, sharing one process's CPU/RAM. On a resource-constrained VPS (e.g. 1GB RAM / 1 CPU) this risks oversubscribing the host with no visibility into how often that happens.

This plan adds an explicit, resource-sized **agent pool**: a priority-aware admission gate that limits how many agents (top-level runs and subagents) can execute at once, sized automatically from detected host/cgroup resources, with an advanced manual override behind a feature flag, full queue/wait telemetry, and a user-facing reporting section. It's the first step toward eventually running each agent in its own sandbox (e.g. Firecracker); this plan deliberately does **not** build that — it builds the admission-control layer against today's in-process execution, shaped so a sandboxed executor can later sit behind the same "slot" abstraction without redoing admission control.

**Confirmed decisions steering this design:**
- Background routines share the *same* pool as chat conversations/subagents (not a separate limit) — routines already call the same `AgentRuntime.start()`.
- Two priority tiers only: **Tier A** (top-level chat turns + routine runs) always admitted ahead of **Tier B** (subagent spawns, any depth) when a slot frees, regardless of arrival order.
- Sandboxing is out of scope for this plan.
- Reporting UI uses stat tiles + inline SVG/CSS bars — no new charting dependency.
- Pool-events log gets size/age-based rotation from day one (not deferred).
- Queued runs are cancelled via the existing Stop button — no new UI affordance needed for "cancel while queued."
- The reporting tab is visible to all users; only the manual override input is gated behind the feature flag.

All claims below were verified directly against the current source (`agent_runtime/_runtime.py`, `agent_runtime/_session.py`, `agent_runtime/_runner.py`, `tasks/_runner.py`).

## Architecture

### New package: `agent_pool/`

A new top-level package (sibling to `agent_runtime/`, `tasks/`) since the pool is shared across `agent_runtime` (top-level + subagents) and `tasks` (routines) — it doesn't belong nested inside either.

```
agent_pool/
  __init__.py    # re-exports: AgentPool, Tier, SlotTicket, PoolClosedError, get_agent_pool()
  _pool.py       # AgentPool, Tier, SlotTicket, _Waiter — the admission gate itself
  _singleton.py  # process-wide singleton + resolve_pool_capacity(), mirrors tasks/_singleton.py's get_store()
  _resources.py  # cgroup/host resource detection + default capacity computation
  _events.py     # PoolEventLog — JSONL writer/reader with rotation
  _reporting.py  # compute-on-read aggregation for the reporting API
```

### Admission gate (`agent_pool/_pool.py`)

Not a plain `asyncio.Semaphore` (FIFO, single priority) — needs two priority queues, cancellable waiters, and live resize.

```python
class Tier(IntEnum):
    TOP_LEVEL = 0   # chat turns + routine runs
    SUBAGENT = 1    # all spawn_agent invocations, any depth

class SlotTicket:
    """Represents 'N of the pool's resource budget,' not a coroutine handle —
    deliberately opaque about *how* the admitted work executes, so a future
    sandboxed executor can hold the same ticket type."""
    def release(self) -> None: ...

class AgentPool:
    def __init__(self, capacity: int, *, event_log: PoolEventLog): ...
    def resize(self, capacity: int) -> None: ...          # grows: drains queues immediately; shrinks: no forced revocation, self-corrects on release
    async def acquire(self, tier: Tier, *, run_id: str, execution_id: str,
                       cancel_event: asyncio.Event | None = None) -> SlotTicket: ...
    async def close(self) -> None: ...                    # cancels all queued waiters
```

Core algorithm — a single `_drain()` method is where priority is enforced: every time a slot frees or capacity grows, it always checks the `TOP_LEVEL` queue before `SUBAGENT`, regardless of how long a `SUBAGENT` waiter has been queued. This is what satisfies the worked example: a subagent queued for a while does *not* jump ahead of a conversation turn submitted afterward, once that turn is queued at the moment a slot opens.

Cancellation reuses `RunSession.stop_event` (already exists) as the `cancel_event` passed to `acquire()` — no new cancellation plumbing needed; stopping a queued run frees its queue position.

### Resource detection (`agent_pool/_resources.py`)

Stdlib only — no new dependency. Must be **cgroup-aware**, not just host-wide, since the app runs in a container:

- Memory: try cgroup v2 (`/sys/fs/cgroup/memory.max`), then cgroup v1 (`/sys/fs/cgroup/memory/memory.limit_in_bytes`, treating the huge unset-sentinel as "unlimited"), then fall back to `/proc/meminfo` `MemTotal`.
- CPU: try cgroup v2 (`/sys/fs/cgroup/cpu.max`), then cgroup v1 (`cpu.cfs_quota_us`/`cpu.cfs_period_us`), then `os.sched_getaffinity(0)` / `os.cpu_count()`.
- Default capacity = `min(memory_budget // PER_AGENT_MEMORY_MB, cpu_count)`, where `memory_budget = detected_memory - SYSTEM_OVERHEAD_MB`, clamped to a minimum of 1. Start `PER_AGENT_MEMORY_MB≈200` and `SYSTEM_OVERHEAD_MB≈300` as named constants (matching the 150-250MB/agent estimate) — flagged for validation against measured RSS-per-run once the pool is live; not blocking initial implementation.

### Wiring into existing call sites

**Tier A — `agent_runtime/_runtime.py`:** `AgentRuntime.__init__` takes `pool: AgentPool | None = None` (default `get_agent_pool()`), passed through to the `AgentRunner` it constructs (mirrors how `browser_runtime` is already threaded, lines 88-97). `start()` (lines 103-115) is **unchanged** — it stays the "is this a valid new run" gate (closed check, per-conversation uniqueness), orthogonal to pool capacity, and still returns a `RunHandle` synchronously without waiting on a slot. `_drive()` (lines 145-164) gets slot acquire/release added around the existing `async with session:` block — acquire before, release in the existing `finally`. This works because `session.add_event()` (`_session.py:94-99`) already falls back to recording locally when the session isn't yet attached to conversation history, so `pool_queued`/`pool_admitted` events emitted *before* `async with session:` still flow through the run's existing SSE event stream (`chat_handler` already starts streaming from `RunHandle.events()` immediately after `start()` returns, before the run has done any real work) — **no new polling endpoint needed for the in-chat queued indicator.**

**Tier B — `agent_runtime/_runner.py`:** `AgentRunner._invoke_child()` (lines 207-232) is the exact insertion point — it already directly `await`s `self.execute(...)` recursively for a subagent. Acquire a `Tier.SUBAGENT` slot after `session.create_child(parent)` (so the child's `execution_id` exists and the queued event can name it) and before `self.execute(...)`; release in a `finally` around that call so a failed child still frees its slot.

**Routines — `tasks/_runner.py` / `tasks/_executor.py`:** `TaskExecutor.run()` already calls the same `AgentRuntime.start()` as chat, so unification is nearly free. Remove the independent admission check in `TaskRunner._tick()` (`tasks/_runner.py:172`, `if len(self._running) >= self._config.max_concurrent: break`) — every ready task result now calls `self._executor.run(...)` immediately, which queues on the shared pool exactly like a chat turn. `TaskRunner._running` remains as pure bookkeeping (cancellation/ownership tracking, `status` property) but stops being an admission gate. `RoutinesConfig.max_concurrent` (`config/__init__.py:143`, `config.yaml:48`) is soft-deprecated: parsed but ignored (log a warning if set to non-default) for one release, then removed. `TaskRunner.status["max_concurrent"]` (`_runner.py:139`) is replaced with the pool's live capacity/active counts.

**Unaffected:** `parallel.max_concurrent` (`config.yaml:41-43`, `agent_core/turn/_execution.py:382`) stays completely independent — it bounds parallel *tool calls within one agent's turn*, not agent-run admission. A `spawn_agent` tool call that clears that semaphore still separately queues on the new pool.

### Event types (`agent_core/events/_models.py`)

Add `PoolQueuedPayload` / `PoolAdmittedPayload` to the existing `AgentEventPayload` discriminated union (same shape as neighboring payloads like `AgentStartedPayload`), fields: `tier: Literal["top_level", "subagent"]`. **Not** added to `conversations/_events_log.py`'s `_PERSISTED_TYPES` allow-list — queued state is transient live-UI state, not conversation content worth persisting per-conversation (mirrors how `content` deltas are excluded today).

### Telemetry (`agent_pool/_events.py`, `agent_pool/_reporting.py`)

New global (cross-conversation) log at `{home_dir}/pool/events.jsonl`, following the existing `{home_dir}/<area>/` storage convention. One flat JSON line per transition: `queued` / `admitted` / `released` / `cancelled` / `capacity_changed`, each with `ts`, `tier`, `run_id`, `execution_id`, and `wait_seconds`/`held_seconds` as applicable. Written open-append-close per line, same accepted cost as `EventsLogWriter`.

**Rotation** (built now, per decision): roll the file over on a size threshold (e.g. 10MB) or age threshold (e.g. 30 days), keeping one prior rotated file (`events.jsonl.1`) — simple truncate-and-rename, no external dependency, small addition alongside the writer.

Reporting uses **compute-on-read** aggregation over the log (no new rollup-job infrastructure, matching the codebase's existing compute-on-read precedent in `TaskRunner.status`): time-at-capacity, saturation-episode count/duration, and per-tier wait-time stats (mean/median/p95), all derivable in one pass by replaying `admitted`/`released`/`capacity_changed` events in order. A live snapshot (current capacity/active/queue-depth) is read directly off the live `AgentPool` instance, no log replay needed.

New route module `server/_pool_routes.py`:
- `GET /api/pool/status` — live snapshot, used by both the settings panel (to show the current auto-detected default) and a live indicator.
- `GET /api/pool/report?since=...` — aggregated historical stats for the reporting tab.

### Settings & feature flag (`settings.py`, `server/_settings_routes.py`, `server/_feature_routes.py`)

Add to `settings.py`'s `_DEFAULTS` / `SettingsUpdate` (following the existing `custom_apps_enabled` pattern exactly):
- `agent_pool_advanced_enabled: bool = False` — the feature flag, live-toggleable, merged into `GET /api/features` alongside `custom_apps_enabled`/`custom_tools_enabled`.
- `agent_pool_size_override: int | None = None` — validated `>= 1`.

Policy: when the flag is off, `resolve_pool_capacity()` ignores any stored override and always uses the auto-detected value — toggling the flag off is a safe, instant return to automatic sizing. `handle_update_settings` gets a post-save side effect (mirroring the existing `reset_provider()` pattern) that calls `apply_pool_capacity_from_settings()` to resize the live pool singleton without a restart whenever either field changes.

### Frontend

- **In-chat queued indicator:** extend the conversation event-stream handling to render a lightweight "Waiting for an available agent slot…" state keyed by `run_id`/`agent_id` on `pool_queued`, cleared on `pool_admitted` (or the first substantive event). For subagents, since the payload carries the child's `execution_id`, this renders on that specific subagent's own card rather than a global banner. The existing Stop button already works to cancel a queued run (mechanically unchanged — it sets the same `stop_event` used as the pool's `cancel_event`) — no new button/copy needed.
- **Settings UI (`SystemSettings.jsx`):** new section using the existing disclosure pattern (`visionAdvancedOpen`, lines 236-290) — a toggle for `agent_pool_advanced_enabled`, and when open, a read-only display of the current auto-detected default (from `GET /api/pool/status`) plus a number input for the override, with a clear warning that misconfiguring it can degrade performance or destabilize the host.
- **Reporting tab (new, visible to all users):** new `server/ui/src/components/agentpool/AgentPoolView.jsx`, following `RoutinesView.jsx`'s polling precedent (`setInterval(load, 5000)` against `GET /api/pool/report`) since there's no push channel for this. Stat tiles (current pool size, active slots, queue depth per tier, time-at-capacity, saturation episode count, per-tier wait percentiles) plus a plain inline `<svg>` bar/sparkline for time-at-capacity history — no charting library. Consult the `dataviz` skill at implementation time for stat-tile/sparkline styling conventions.

## Phased implementation order

1. **Core pool + resource detection** (`agent_pool/_pool.py`, `_resources.py`, `_singleton.py`, `_events.py` with rotation) — fully unit-testable in isolation, no wiring yet.
2. **Wire Tier A + Tier B** (`agent_runtime/_runtime.py`, `agent_runtime/_runner.py`, new event payloads) — this alone delivers the core concurrency-limiting value, defaulting to auto-detected capacity.
3. **Unify routines** (`tasks/_runner.py` gate removal, `RoutinesConfig.max_concurrent` deprecation).
4. **Settings & feature flag** (`settings.py`, `server/_settings_routes.py`, `server/_feature_routes.py`, `SystemSettings.jsx`).
5. **Telemetry & reporting API** (`agent_pool/_reporting.py`, `server/_pool_routes.py`).
6. **Frontend** (in-chat queued indicator, `AgentPoolView.jsx`).

## Critical files

- `agent_runtime/_runtime.py` — `AgentRuntime.start()`/`_drive()`, pool wiring for Tier A
- `agent_runtime/_runner.py` — `AgentRunner._invoke_child()`, pool wiring for Tier B
- `agent_runtime/_session.py` — `RunSession.add_event()`/`create_child()` (no changes needed, but the design depends on their current behavior)
- `tasks/_runner.py` — `TaskRunner._tick()`, admission-gate removal
- `agent_core/events/_models.py` — new `PoolQueuedPayload`/`PoolAdmittedPayload`
- `settings.py` — new settings fields
- `server/_settings_routes.py`, `server/_feature_routes.py` — settings/flag wiring
- `server/ui/src/components/SystemSettings.jsx` — override UI
- New: `agent_pool/` package, `server/_pool_routes.py`, `server/ui/src/components/agentpool/AgentPoolView.jsx`

## Verification

- **Unit tests** (`tests/unit/agent_pool/`): priority-drain correctness (the critical case — a later-arriving Tier A waiter must be admitted ahead of an earlier, still-queued Tier B waiter when a slot frees), FIFO within a tier, cancellation freeing a queue slot, resize up/down semantics, resource-detection fallback across cgroup v2 / v1 / no-cgroup fixtures, and reporting aggregation against synthetic log sequences.
- **Integration tests**: construct `AgentRuntime` with a small-capacity pool, confirm a second run for a different conversation queues (`pool_queued` event appears before `pool_admitted`/`agent_started`) and is admitted once the first releases or is stopped; confirm `_invoke_child` releases its slot on both success and failure paths; confirm routine task pickup after the `_tick()` gate removal still respects the shared pool via a small-capacity pool injected into a test runtime.
- **Manual verification**: run `just dev`, set a low override (e.g. 1) via the new settings UI with the flag enabled, open two chats and confirm the second shows "waiting for an available agent slot" until the first finishes; trigger a `spawn_agent` call and confirm it queues behind an already-full pool and gets admitted ahead of a subsequently-submitted queued subagent once a top-level run is also waiting; check `just lint` / `just typecheck` / `just unit` pass.
