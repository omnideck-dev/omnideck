---
title: Integrations Architecture
type: concept
tags: [integrations, catalog, operations, grants, oauth]
created: 2026-07-07
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "integrations/"
  - "server/_integrations_routes.py"
  - "server/_integrations_oauth_routes.py"
  - "server/_brokering.py"
---

# Integrations Architecture

## Overview

An **integration** is a credentialed connection to an external service (Gmail,
iCloud, Google Workspace, or any custom HTTP API) that agent tools can call.
This page covers the **application layer**: the catalog of installable
presets, the canonical operation IDs tools invoke, and the per-connection
permission grants a user sets. The actual credential storage, broker
subprocess lifecycle, and wire protocol live one layer down in
[[Credential Brokering]] — this package (`integrations/`) never touches
decrypted secrets itself.

This is a real package split, confirmed by `integrations/__init__.py`'s own
docstring: *"Application callers use `integrations.service`. Credential
storage, process lifecycle, and transport clients belong to `brokering`."*
Formerly, integration and broker concerns lived together under
`integrations/supervisor/` and `integrations/brokers/`; that code has moved to
the standalone `brokering/` package, and `integrations/` now holds only the
catalog/policy/application layer described here.

## How It Works

### 1. Catalog

`integrations/catalog/_defaults.py` defines `IntegrationCatalogEntry` presets:
`icloud`, `gmail`, `google_workspace`, `http` (generic REST), and a
development-only `test` entry gated by `OMNIDECK_ENABLE_TEST_INTEGRATIONS`.
Each entry names a `BrokerDriver` (which broker subprocess to spawn — see
[[Credential Brokering]]), the operations it unconditionally exposes, and for
OAuth-scoped entries like `google_workspace`, a `scope_operations` map from a
granted OAuth scope to the operation IDs it unlocks.

### 2. Canonical Operations

`integrations/operations.py` defines `NATIVE_OPERATIONS` — a flat, versioned
list of operation IDs (`email.messages.send`, `calendar.events.create`,
`drive.files.upload`, `http.request`, …) grouped by namespace
(`OPERATIONS_BY_GROUP`). An operation ID is the single stable contract shared
across the integration service, broker RPC dispatch, and persisted grants —
the LLM-facing tool name in `tools/integrations/` is a presentation detail
layered on top of the same ID.

### 3. Availability vs. Grants

Two distinct sets govern whether an agent can call an operation on a
connection:

- **Available operations** — what the connected account's scopes/plan make
  possible at all. Computed by `IntegrationCatalogEntry.resolve_operations()`
  from the entry's unconditional `operations` plus any `scope_operations`
  unlocked by the OAuth scopes actually granted.
- **Agent operation grants** (`integrations/operation_grants.py`) — the exact
  subset of available operations the user has explicitly allowed the agent to
  use for this connection, persisted per-connection and enforced broker-side
  (see [[Credential Brokering]]). `normalize_operation_grants()` always
  intersects a requested grant set against what's currently available, so a
  stale grant can never outlive the scope that unlocked it.

### 4. Invocation

`integrations/service.py`'s `IntegrationService` is the only supported entry
point for application code:

- `list_connections()` — calls `brokering.supervisor_client` to list
  non-secret connection metadata (id, slug, kind, grants, state).
- `invoke(connection_id, operation_id, arguments)` — validates the operation
  ID is a known canonical operation, then calls `brokering.broker_client`,
  which resolves the connection to a live broker socket and sends the
  operation as the RPC `verb`.

`integrations/connection_cache.py`'s `IntegrationConnectionCache` polls
`list_connections()` on a timer (default every 5s) and publishes immutable
snapshots for tool discovery, so a running turn's view of "which integrations
exist and what are they allowed to do" doesn't require a supervisor round
trip per tool call.

### 5. Calendar References

Calendar operations deal with provider-specific identifiers (CalDAV hrefs +
`RECURRENCE-ID`, Google event IDs) that the agent shouldn't need to
understand. `integrations/calendar_refs.py` and `calendar_recurrence.py`
define an opaque, base64-encoded reference type that brokers emit and decode
internally — the agent passes the reference back verbatim; it never
constructs or parses one.

### 6. HTTP Surface

- `server/_integrations_routes.py` — CRUD for connections (list catalog, add,
  update grants/label, remove, reconnect with new credentials).
- `server/_integrations_oauth_routes.py` — the loopback OAuth start/callback/
  status flow for scoped providers (Google Workspace), separate from the CRUD
  routes; both call through `server/_brokering.py`'s `supervisor_call()`
  helper, which wraps `brokering.supervisor_client.call()` with a 90s timeout
  (generous enough for a credential prepare/activate round trip).

## Where It Lives

| Path | Role |
|------|------|
| `integrations/catalog/` | `IntegrationCatalogEntry` presets (`icloud`, `gmail`, `google_workspace`, `http`, `test`) |
| `integrations/operations.py` | Canonical operation ID registry, grouped by namespace |
| `integrations/operation_grants.py` | Grant validation/normalization against available operations |
| `integrations/service.py` | `IntegrationService` — the supported application API |
| `integrations/connection_cache.py` | Polling cache publishing immutable connection snapshots |
| `integrations/calendar_refs.py`, `calendar_recurrence.py` | Opaque calendar event/series references |
| `server/_integrations_routes.py` | HTTP CRUD routes |
| `server/_integrations_oauth_routes.py` | OAuth start/callback/status routes |
| `server/_brokering.py` | Shared `supervisor_call()` helper for both route families |
| `tools/integrations/` | Agent tool wrappers around `IntegrationService.invoke()` |

## Key Details

- **`integrations/` never imports broker internals directly except through
  `brokering`'s public client modules** (`broker_client`, `supervisor_client`)
  — it has no access to the vault, master key, or raw credentials.
- **Grants are re-validated against availability on every update**, not just
  at creation — if a user later narrows the OAuth scopes they grant (e.g. via
  re-auth), stale grants for now-unavailable operations are silently dropped
  rather than enforced incorrectly.
- **The `test` catalog entry is deliberately registered in production code**
  (gated by an env var, not a build flag) so the full invocation path
  (service → broker client → broker) is exercised in E2E tests without a
  separate test-only code path.

## Open Questions

- Per-integration egress allowlisting is a planned hardening item (see
  `plans/`, which isn't authoritative for current behavior).
- Whether `google_workspace` will be the template for further OAuth-scoped
  providers, or whether each gets its own catalog/broker pairing, wasn't
  resolved in source alone.

## Sources

- `docs/integrations.md` — package-boundary and terminology reference
