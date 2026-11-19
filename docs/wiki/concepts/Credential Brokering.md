---
title: Credential Brokering
type: concept
tags: [brokering, security, broker, supervisor, vault, process-isolation]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "brokering/"
---

# Credential Brokering

## Overview

`brokering/` is the process-isolation and credential-custody subsystem
underneath [[Integrations Architecture]]. It owns an encrypted vault, spawns
and supervises one subprocess per credentialed connection, and brokers all
traffic to that connection's upstream over a private Unix Domain Socket — so
neither the main app process nor the agent ever holds a decrypted secret in
its own memory. As of this page, it's used for two kinds of connections that
share the same platform: **tool integrations** (Gmail, iCloud, Google
Workspace, generic HTTP) and **model-provider connections** (OpenAI,
Anthropic, OpenRouter, OpenAI-compatible) — LLM API keys are now brokered the
same way integration credentials are, via a dedicated `llm_proxy` broker that
transparently forwards HTTP traffic while injecting the real auth header.

This package was split out of what used to be `integrations/supervisor/` and
`integrations/brokers/`. If you're looking for that code by its old path, it
now lives here.

## How It Works

### 1. Process Model

```
computron (UID 1000)              broker (UID 1001)
──────────────────────            ──────────────────
aiohttp app ──supervisor_client──►  Supervisor
  agent tools ──broker_client───►     ├── app.sock (CRUD: add/list/resolve/update/remove/reconnect)
    via /run/cvault/*.sock             ├── BrokerManager (spawn/watch/respawn)
                                       ├── encrypted vault (AES-256-GCM)
                                       └── one subprocess per connection:
                                             email_broker (IMAP/SMTP/CalDAV)
                                             google_workspace_broker (OAuth + Google APIs)
                                             http_broker (generic REST)
                                             llm_proxy (model-provider HTTP proxy)
                                             test_broker (dev/E2E fixture)
```

`computron` is in the `broker` OS group, which lets it connect to broker
sockets but not read the vault directory (mode `0700`, owned by `broker`).

### 2. Supervisor Startup

`brokering/supervisor/_lifecycle.py`'s `Supervisor.start()`:
1. Validates the catalog and its host-path bindings (`validate_catalog`,
   `validate_host_path_bindings`) — a typo in a catalog entry's host-path role
   fails boot, not the first spawn.
2. Loads or generates the master key (`_crypto.load_or_init_master_key()`).
3. Runs vault schema migrations (`brokering/migrations/`).
4. **Reconciles every persisted connection from disk before binding the
   listener** — `_reconcile_from_disk()` concurrently respawns a broker per
   vault entry, so the first RPC client ever sees a fully-warmed registry.
   A single connection's reconcile failure (bad catalog drift, undecryptable
   blob) is logged and isolated; it doesn't block the others or the
   supervisor's own startup.
5. Binds `app.sock` and serves RPC.

### 3. Vault & Encryption

`brokering/supervisor/_crypto.py`: the master key is 32 random bytes, written
once to `<vault>/.master-key` (mode `0600`), never rotated. Each connection's
secrets are AES-256-GCM encrypted with a fresh 12-byte nonce per write and the
connection ID as AAD — binding ciphertext to filename means renaming
`gmail.enc` to `icloud.enc` on disk makes it fail to decrypt. A 1-byte version
header is reserved for a future scheme to coexist with this one. Non-secret
metadata (id, slug, label, grants, timestamps) lives in a sibling plaintext
`.meta` file — see `ConnectionMeta` in `brokering/supervisor/types.py`, which
discriminates `IntegrationConnectionMeta` (carries `agent_operation_grants`)
from `ModelProviderConnectionMeta` (deliberately has none — a model provider
is not something the agent "invokes an operation" on).

### 4. Broker Lifecycle (`BrokerManager`)

`brokering/supervisor/_manager.py`'s `BrokerManager` is the one place every
spawn path goes through: `add` (new connection), `reconcile_existing`
(boot-time rehydrate), and crash respawn. Each running broker has a watcher
task; two terminal states stop its respawn loop:

- **`auth_failed`** — broker exited with code `77` (upstream rejected
  credentials). No respawn — hammering a rejecting auth endpoint risks
  upstream rate-limiting; the user must reconnect with new credentials.
- **`broken`** — three consecutive non-77 failures. Likely a config bug or
  dead network path.

Generic crash respawn uses exponential backoff: 1s → 2s → 4s → 8s → 16s,
capped at 30s. `reconnect()` can either hand a live broker new credentials
in place (via the control protocol, §6) or start a fresh broker if none is
healthy — tool-integration reconnects preserve the user's exact operation
grants; model-provider reconnects have none to preserve.

### 5. Spawn

`brokering/supervisor/_spawn.py`'s `spawn_broker()` launches the catalog
entry's `BrokerDriver.command`, injecting the entry's static `driver_config`
plus the connection's decrypted secret fields as env vars (mapped via
`driver.env_injection`), and any `HostPathBinding`-declared directories
(e.g. a shared downloads dir) as additional env vars. It waits up to 30s for
the child to print `READY\n` on stdout (the control-channel handshake, §6);
an early exit surfaces its exit code so the caller can distinguish
`77`/auth-fail from a generic crash.

### 6. Wire Protocols

Two distinct channels, deliberately separate:

- **RPC socket** (`brokering/_rpc.py`) — length-prefixed JSON frames over a
  UDS. `broker_client.call()` makes two hops: resolve the connection ID to a
  broker socket path via the supervisor's `app.sock`, then send the operation
  ID as the frame's `verb` directly to that broker. `supervisor_client.call()`
  talks the same framing to `app.sock` for `add`/`list`/`resolve`/`update`/
  `remove`/`reconnect`.
- **Control pipes** (`brokering/_control.py`) — inherited stdin/stdout between
  supervisor and child, *not* exposed on the public RPC socket. Used for
  `prepare_credentials` / `activate_credentials` / `discard_credentials` (a
  three-phase live credential swap so a bad replacement never clobbers a
  working connection) and live `grants` updates. The child prints `READY` on
  stdout at startup (`brokering/_ready.py`) as the spawn handshake; broker
  logs must stay on stderr so they never collide with control frames.

### 7. Broker Processes

All under `brokering/brokers/`, sharing `_common/_runtime.py`'s
`run_integration_broker()` harness:

| Broker | Upstream | Notes |
|--------|----------|-------|
| `email_broker` | IMAP/SMTP/CalDAV (Gmail, iCloud) | Reconnects once on a stale IMAP session before failing |
| `google_workspace_broker` | Gmail/Calendar/Drive/Contacts via OAuth | Refreshes candidate OAuth credentials before activating them, so a bad refresh never replaces a working token |
| `http_broker` | Generic REST | Static bearer/header token, user-configured base URL |
| `llm_proxy` | OpenAI/Anthropic/OpenAI-compatible | Not a verb-dispatch broker — a transparent HTTP proxy; see below |
| `test_broker` | None (in-memory) | Deterministic fixture for E2E, gated by `OMNIDECK_ENABLE_TEST_INTEGRATIONS` |

**`llm_proxy` is architecturally distinct** from the others: instead of
dispatching RPC verbs, it runs its own `aiohttp` server bound to the broker's
UDS and transparently forwards every request to the provider's real base URL,
stripping the SDK client's placeholder auth header and injecting the real API
key (`Authorization: Bearer …` or `x-api-key` for Anthropic). Streaming
(SSE/chunked) responses pass through unmodified, chunk by chunk. The request
body size cap is disabled (`client_max_size=0`) because a long conversation's
full transcript can exceed aiohttp's 1 MiB default. The app's LLM SDK client
talks to this local proxy socket instead of the real provider endpoint
directly, so the API key never enters the app or agent process's memory —
`ModelProviderCatalogEntry` in `brokering/brokers/llm_proxy/catalog.py`
defines the `llm_openai`, `llm_anthropic`, `llm_openrouter`, and
`llm_openai_compat` presets, all sharing this one driver.

### 8. Permissions Hardening

`brokering/_perms.py` centralizes every filesystem mode as a named constant
(`VAULT_FILE_MODE=0o600`, `VAULT_DIR_MODE=0o700`, `SOCKET_MODE=0o660`,
`RUNTIME_DIR_MODE=0o750`) so the supervisor/broker Python code and
`container/entrypoint.sh`'s root-level chown/chmod stay in lockstep — the
comment on this module is explicit that changing one without the other
reopens the hole it closes. `PROCESS_UMASK=0o077` is set at the top of every
supervisor/broker `__main__`, and `disable_core_dumps()` hard-caps
`RLIMIT_CORE` to zero so a crashed broker (holding decrypted credentials in
memory) never writes a readable core dump to disk.

## Where It Lives

| Path | Role |
|------|------|
| `brokering/supervisor/` | `Supervisor`, `BrokerManager`, vault crypto, registry, `app.sock` handler |
| `brokering/brokers/` | Per-provider broker subprocess implementations |
| `brokering/broker_client/` | App-side helper: resolve + invoke an operation on a connection |
| `brokering/supervisor_client/` | App-side helper: CRUD calls to the supervisor |
| `brokering/catalog.py`, `_catalog_validation.py` | Combines integration + model-provider catalogs; validates host-path bindings |
| `brokering/drivers.py` | `BrokerDriver` / `HostPathBinding` — the launch contract a catalog entry declares |
| `brokering/_rpc.py` | Length-prefixed JSON frame read/write over UDS |
| `brokering/_control.py` | Private stdin/stdout credential-swap and live-grant protocol |
| `brokering/_perms.py` | Canonical filesystem mode constants + core-dump hardening |
| `brokering/_session_slot.py` | Holds a broker's "current" active session across a live credential swap |
| `brokering/connection_data.py` | `BrokerConnectionData` — the in-memory secret bundle shape |
| `brokering/migrations/` | Vault schema upgrades, run before any broker/listener starts |

## Key Details

- **Vault writes are not transactional across files.** `.meta` and `.enc`
  are each written atomically, but the pair isn't; several call sites
  (`BrokerManager.add`, `_update_credentials`, `_start_reconnected_broker`)
  have explicit comments reasoning through which write must land first so a
  crash mid-operation leaves a recoverable (not silently-wrong) state.
- **The RPC socket and the control pipes are intentionally different
  channels** — the control protocol (credential swap, live grants) must never
  be reachable from the same socket agent tools use to invoke operations.
- **One `_serialize_connection_mutation` decorator in `BrokerManager`** holds
  a per-connection asyncio lock around every mutating verb, so concurrent
  `update`/`reconnect`/`remove` calls on the same connection can't interleave.

## Open Questions

- Master-key rotation is not implemented (same gap noted in the prior version
  of this page, still true in current source).
- Whether additional `ModelProviderCatalogEntry` protocols beyond
  `openai`/`anthropic` are planned wasn't resolved from source alone.

## Sources

- `docs/integrations.md` — predates the `brokering/` split but still describes
  the shared security model (UID separation, vault encryption, write gating)
