# Integrations

## What an integration is

An *integration* defines a supported external service and its operations. A
*connection* is one configured account or endpoint for that integration. For
example, Google Workspace is an integration; "Work Google account" is a
connection. Multiple connections can use the same integration.

| Term | Meaning | Code |
|---|---|---|
| Integration | A supported service preset and its operations | `IntegrationCatalogEntry` |
| Connection | One configured account or endpoint, with its own ID and state | `BrokeredConnectionMeta`, `BrokeredConnectionRecord` |
| Integration connection | A connection with explicit agent operation grants | `IntegrationConnectionMeta` |
| Model-provider connection | A brokered LLM provider, without integration operation grants | `ModelProviderConnectionMeta` |
| Broker | The implementation executing authenticated upstream requests | `brokering.brokers` |
| Operation | A stable application action, independent of its LLM-facing wrapper | `IntegrationOperation` |
| Grant | Permission to invoke a specific operation through a connection | `OperationGrants` |

Use `connection_id` for internal references to a configured connection and
`slug` for its catalog entry. Do not use "instance" as another name for a
connection. The UI feature remains **Integrations**, with **Add integration**
as the setup action and **Connection** for account/authentication details.

| Provider | Operations | Auth |
|---|---|---|
| iCloud | Email (IMAP + SMTP) + Calendar (CalDAV) | App-specific password |
| Gmail | Email (IMAP + SMTP) | App-specific password |
| Google Workspace | Gmail, Calendar, Drive, Contacts | Desktop OAuth |
| Custom HTTP API | One authenticated HTTP request operation | Static token |

Granted operations on running connections become agent tools —
`list_email_messages`, `move_email`, `send_email`, `list_calendars`, `list_events`,
etc. Their existing model-facing argument remains `integration_id` (e.g.
`"icloud_personal"` or `"gmail_work"`); it identifies a **connection**, not a
catalog entry. Keeping that argument stable avoids changing saved or replayed
tool-call payloads as part of an internal naming cleanup.
LLM-facing descriptions and valid-ID lists consistently call these
**integration IDs**, matching `integration_id`; "connection" remains an internal
and setup-UI term, not an alternative name in tool parameter documentation.

### Application service and package boundaries

`integrations.service.IntegrationService` exposes two methods:

- `list_connections()` returns non-secret connection records, including
  status, available operation descriptors, and granted operation IDs.
- `invoke(connection_id, operation_id, arguments)` returns the
  operation's structured result. Broker dispatch enforces the grant.

`IntegrationConnectionCache` polls this service for immutable discovery snapshots;
agent adapters select tools from those snapshots and use the service for invocation.
The adapters own LLM-facing formatting; the service uses clients in `brokering`
to reach the supervisor and brokers. Custom-app access is not implemented.
A future SDK will need authenticated app identity, per-app grants, and enforcement
at a trusted boundary; the current service uses connection-level grants only.

The supervisor's `list` RPC and `GET /api/integrations` return
`{"connections": [...]}`. They no longer emit the duplicate `integrations`
field. In contrast, `GET /api/integrations/catalog` returns
`{"integrations": [...]}` because it lists integration definitions.

Internal Python names and the connection-list response changed together.
Existing ID values, metadata JSON fields, operation IDs, vault/socket paths,
HTTP endpoint URLs, and `config.integrations` keys remain unchanged. The
broker launch variable `INTEGRATION_ID` and OAuth status field `integration_id`
also retain their existing wire names; both carry connection IDs. No saved-data
migration is needed for these terminology changes.

### Discovery lifecycle and run snapshots

The server constructs one `IntegrationConnectionCache` from
`integrations/connection_cache.py`, stores it under the typed
`INTEGRATION_CACHE_KEY`, and injects it into `AgentRuntime`. It runs on the
existing application event loop, not in another process or one poller per
connection. Lower-level packages do not import the server or look up a global
cache.

- **Startup:** after migrations, start polling before the aggregate readiness
  gate. The first successful fetch (including zero connections) releases the
  integration gate. After 30 seconds the gate releases even if discovery is
  unavailable; polling continues so the app can recover later.
- **Polling:** fetch a complete connection list, then wait five seconds or
  until an explicit refresh request. Each request has a five-second deadline
  that cancels the actual fetch, not just its caller's wait.
- **Connection edits:** successful add, update, reconnect, remove, and OAuth
  completion await a post-mutation refresh before responding. Requests arriving
  during an older fetch trigger a subsequent fetch; they cannot be satisfied
  by the pre-edit response. Concurrent refresh requests can share that fetch.
- **Failure:** discovery becomes unavailable and publishes an empty snapshot
  for new runs. Polling retries automatically. A successful mutation remains
  successful even if its follow-up discovery fails.
- **Shutdown:** after stopping routine execution and agent runs, cancel and
  await the polling task, outstanding request, and startup waiters.

Snapshots are tuples of frozen `IntegrationConnection` records with frozen
operation grants. At run admission, `AgentRuntime` captures one snapshot in
`RunSession`. Root and child agents use that snapshot, and each agent resolves
its tool categories once. Its initial, restored, and dynamically loaded skills
all resolve against the same categories. Reading a snapshot or resolving a
skill never queries the supervisor. UI tool-category requests use the current
application snapshot instead of a run snapshot.

Already-running agents keep their advertised integration tools even when the
shared cache changes. New runs pick up the latest snapshot. This does not
freeze authorization: broker checks remain live, so revoked grants, removed
connections, or upstream failures can still make an advertised tool call fail.
There is no subscription protocol, revision counter, or persisted cache.

### Calendar tool contract

Google Workspace and CalDAV integrations share one agent-facing calendar surface:

- `list_calendars` returns an opaque `calendar_ref` for each calendar.
- `list_events` expands recurring events and returns an `event_ref` for the exact listed occurrence. Recurring rows also carry a `series_ref`.
- `search_events` searches a calendar by text over a configurable date range and returns the same occurrence-aware references as `list_events`.
- `create_event` takes `calendar_ref` and returns the created event's `event_ref`. An optional RFC 5545 `recurrence_rule` creates a series and also returns `series_ref`; recurring timed events require an IANA `time_zone` so they remain at the intended local time across daylight-saving transitions.
- `update_event` and `delete_event` take only `event_ref`; on recurring events they affect exactly one occurrence.
- `update_event_series` and `delete_event_series` take only `series_ref` and affect the entire recurring series.

Supplying `attendees` creates scheduling attendees rather than description metadata. Google requests guest notifications explicitly; CalDAV events include organizer and attendee scheduling properties so servers that implement CalDAV scheduling can deliver invitations and subsequent changes.

Provider IDs, CalDAV hrefs, and `RECURRENCE-ID` values stay inside the opaque references. This keeps the tool choice explicit: occurrence tools cannot accidentally imply a whole-series mutation, and the agent never has to combine a calendar ID with an event ID itself.

---

## Process model

Three OS users at runtime:

| User | UID | Owns |
|---|---|---|
| `omnideck` | 1000 | The aiohttp app, the agent, the browser tools, all user-uploaded files |
| `broker` | 1001 | The supervisor, every broker subprocess, the encrypted vault, runtime sockets |
| `root` | 0 | Container init only — drops to the two above via `gosu` in `entrypoint.sh` |

`omnideck` is in the `broker` group, so it can `connect()` to the broker sockets at `/run/cvault/`. It can't read the vault directory (`/var/lib/omnideck/vault`, mode `0700` `broker:broker`).

The supervisor runs as a long-lived process that owns:

- The encrypted credential store under `/var/lib/omnideck/vault/`.
- One **broker subprocess per connection**, including brokered model providers. Brokers are independent processes that hold the decrypted credential in their own memory and connect directly to the upstream provider (Gmail's IMAP, iCloud's CalDAV, etc.).
- The `app.sock` UDS at `/run/cvault/app.sock`. The aiohttp app talks to this when the user adds, edits, or removes an integration.

```
┌─────────────────────────────────────────────────────────────┐
│ container                                                   │
│                                                             │
│  omnideck (UID 1000)               broker (UID 1001)        │
│  ────────────────────              ──────────────────       │
│  aiohttp app                       supervisor               │
│   │ (HTTP routes,                   │ (vault, spawn,        │
│   │  agent runtime)                 │  RPC dispatch)        │
│   │                                 ├── email_broker[icloud]│
│   ├── /api/integrations ───────────►│      │  imap+smtp     │
│   │   (PATCH/DELETE/POST)           │      │  TLS to icloud │
│   │     via app.sock                │      ↓                │
│   │                                 │   imap.mail.me.com    │
│   │                                 │                       │
│   ├── tool_call ───────────────────►├── email_broker[gmail] │
│   │   via per-broker socket         │      │  imap+smtp     │
│   │   /run/cvault/<id>.sock         │      ↓                │
│   │                                 │   imap.gmail.com      │
│                                                             │
│  /var/lib/omnideck/vault/ (mode 0700 broker:broker)         │
│  /run/cvault/                       (mode 0750 broker:broker)
└─────────────────────────────────────────────────────────────┘
```

The agent UID cannot open the vault. Brokers remove captured startup fields
from `os.environ` after reading them into runtime state. This is best-effort
cleanup, not erasure of the original exec-time environment exposed through
`/proc`; credential isolation depends on the OS-user boundary.

---

## Operation grants

Every callable integration action has a stable canonical operation ID, such
as `email.messages.search`, `calendar.events.create`, or `http.request`. A
connection stores the exact operation IDs granted to the agent; new
connections created by the setup UI have no grants until the user finishes
Review. Selecting tools alone does not persist those grants.

Two layers apply the same policy:

1. **Broker-side gate (the security boundary).** The supervisor passes the
   exact operation grants to the broker at spawn. The shared broker dispatcher
   accepts canonical operation IDs directly in the RPC `verb` field and returns
   `PERMISSION_DENIED` unless that ID is granted. This applies even to a caller
   that reaches a broker socket directly.
2. **App-server projection (tool discovery).** Agent tool adapters are built
   only for granted operations on running connections. This keeps ungranted
   operations out of the model's tool list; it does not replace the broker gate.

Grant edits are persisted and sent over private inherited stdin/stdout pipes;
the broker acknowledges replacing its in-memory allowlist without restarting
or reconnecting upstream. The public operation socket has no grant-update verb.
Subsequent authorization checks use the new grants; already-authorized calls
may finish. Edits serialize with reconnect, removal, and crash respawn. If the
control handoff fails or is cancelled, the supervisor stops the broker and keeps
the saved requested policy for recovery instead of restoring revoked access.
If persistence itself fails, the edit is not saved and the broker is stopped.
Healthy brokers also accept credential replacements over this control channel:
prepare a candidate, persist the accepted fields, then activate it. Preparation
rejection leaves the running connection and vault unchanged. Email authenticates
the configured IMAP/SMTP/CalDAV clients; Google refreshes candidate OAuth tokens.
HTTP and model proxies validate local configuration only, not upstream access.
No credentials are echoed in acknowledgments or control errors.

Activation switches subsequent calls to the new connection and closes old
clients immediately; in-flight operations may fail and are not automatically
retried by the update protocol. There is no graceful draining. A failed or
cancelled control handoff stops the uncertain child. Recovery uses the credentials
saved on disk (old before persistence, new after persistence). A storage error
attempts to restore the old vault data and discard the candidate; failure of that
recovery leaves the broker stopped. Vault secrets and metadata are not a single
crash-atomic transaction. A degraded/brokerless connection starts one broker with
the replacement credentials and saves them only after READY. Startup failure or
cancellation leaves the saved credentials unchanged, with no retry using old
credentials. A save failure stops the candidate. Metadata (only its timestamp
changes) is written before the atomic credential write, so a failed save cannot
replace the old credentials; restoring the timestamp is best-effort.

Legacy capability/read-write fields are understood only by the
versioned vault migration. Live API requests must use operation grants; stale
clients receive a refresh-required error instead of permission translation.

OAuth scopes limit the operations offered and accepted during configuration.
Startup, crash recovery, and credential reconnect pass the saved grants to the
broker unchanged; they do not intersect them with scope availability. Narrower
remote authorization can therefore cause an enabled operation to fail upstream
until the user reconnects with suitable consent or changes the tool selection.

---

## Broker sessions and shared lifecycle

A **broker session** is the provider-specific runtime state used to serve
requests. It is not the persisted integration connection record, an agent/chat
session, or necessarily a network connection. There is no universal session
base class; brokers share a lifecycle, not identical contents.

| Broker | Session object and resources |
|---|---|
| Email | `VerbDispatcher` with configured, authenticated IMAP/SMTP/CalDAV clients |
| Google Workspace | `VerbDispatcher` backed by refreshed OAuth credentials; API services are built per request |
| HTTP | `VerbDispatcher` with request/auth settings and an owned `aiohttp.ClientSession` |
| LLM proxy | Immutable `ProxyCredentials`; its process-wide HTTP client survives session replacement |
| Development test broker | Reused `VerbDispatcher` preserving simulated upstream state across credential updates |

Each broker supplies a `create_session(connection_fields, ...)` async context
manager. Entering it prepares the provider-specific object; exiting it performs
cleanup. `connection_fields` contains broker configuration and credentials.
Factories must also clean up partially created resources if preparation fails.

- **`brokering._session_slot.BrokerSessionSlot`** owns the active session.
  `prepare()` builds a candidate without changing `session_slot.current` and
  returns `PreparedBrokerSession` callbacks. Activation publishes the new session
  and closes the old one; discard closes only the candidate. There is no draining
  or automatic retry, so retiring old clients can interrupt in-flight calls.
- **`brokering._control.BrokerControl`** owns the pending update ID and decides
  which candidate to activate or discard in response to supervisor commands.
  It does not interpret the provider-specific object or write the vault. The
  wire commands remain `prepare_credentials`, `activate_credentials`, and
  `discard_credentials`; session terminology changes only internal Python names.
- **`brokering.brokers._common._runtime.run_integration_broker`** wraps the
  factory to apply current operation grants and routes
  each operation through the active dispatcher. This `Dispatcher` protocol is
  specific to integrations. The LLM proxy reuses the session slot and control
  protocol directly, without integration operation grants or a dispatcher.

Startup and credential replacement use the same factory. Prepared callbacks
must be activated or discarded once: control enforces this with its pending
update ID, while startup activates directly. The supervisor remains responsible
for persistence and for stopping the broker after an ambiguous control failure.

## How credentials are stored

Per-connection files in the vault directory:

```
/var/lib/omnideck/vault/
├── .master-key                      # 32-byte AES-256 key, mode 0600
├── .migrations.json                 # vault migration completion ledger
└── creds/
    ├── icloud_personal.meta          # non-secret version-3 metadata
    ├── icloud_personal.enc           # encrypted credential bundle
    ├── icloud_personal.meta.pre-v3.bak # original legacy metadata, if migrated
    ├── gmail_work.meta
    └── gmail_work.enc
```

The plaintext blob is a JSON object represented by `BrokerConnectionData` —
for app-password integrations, it contains `{"email": "...", "password": "..."}`.
At spawn, the supervisor decrypts it and uses the catalog driver's bindings to
pass fields such as `EMAIL_USER` and `EMAIL_PASS` through the environment.
Healthy credential replacements instead use the private control pipes. Neither
path sends credentials to the LLM tool adapter.

**Encryption details:**

- AES-256-GCM. Random 12-byte nonce per blob, prepended to the ciphertext.
- AAD = the connection ID, so re-using a stale blob under a different name would fail to decrypt.
- A version byte at the start (`0x01`) reserves room for future format changes.
- The master key is a 32-byte CSPRNG output, written once to `.master-key` on
  first supervisor boot. Automatic key rotation is not implemented.

The master key is on local disk at mode `0600 broker:broker`. If an attacker can read that file *and* the `.enc` blobs, they have your credentials. Treat the `/var/lib/omnideck/vault/` volume the same way you'd treat a password-manager backup.

### Metadata migration and startup recovery

`brokering.migrations` owns the vault migration plan and uses the shared
`migrations._engine` runner with a vault-local completion ledger. Before any
broker starts or `app.sock` accepts requests, legacy version-1/2 metadata is
converted to version 3. Historical read/write mappings are frozen: future
operations cannot silently expand old selections. Model-provider records have
no operation grants. Legacy read-only HTTP access becomes no grant because
`http.request` cannot enforce a read-only subset; the user must explicitly
enable that tool again.

Migration backs up each original `.meta` file once, preserves IDs and encrypted
`.enc` files, and can resume after a partial failure. A migration error prevents
supervisor startup rather than serving partially upgraded state. See
[migrations](migrations.md) for the migration runner and ledger contract.

After migration, startup loads connections with both metadata and credentials.
Broker startup failures retain an `auth_failed` or `broken` record for recovery.
Missing catalog entries, invalid current metadata, or unreadable credentials
are logged and skipped; their files remain, but they are not visible in the
runtime registry. Saved grants are not reduced to current OAuth scopes.

---

## State machine

Each connection has a state visible in the UI. Transitions are driven by broker process events (the supervisor watches `proc.wait()` exit codes) and user actions.

| State | Meaning | UI affordance |
|---|---|---|
| `running` | Broker reached READY; HTTP/model proxies validate local configuration, not upstream credentials | Green dot, label `connected` |
| `auth_failed` | Broker exited with code 77 — upstream rejected the credential | Red status and reconnect action |
| `broken` | Broker unavailable after startup, reconnect, control/persistence failure, or exhausted crash recovery | Red status and reconnect action |

Auto-restart policy:

- **`auth_failed`** is sticky. The supervisor stops respawning. Recovery uses
  reconnect, which replaces credentials while retaining
  the user's exact grants, even if the new authorization has narrower scopes.
- **Generic crashes** (anything except exit 77) trigger backoff respawn. The
  watcher stops at three consecutive failures, giving retries after 1s and 2s
  with the current threshold. A successful READY resets the failure count.
- **Idle drops** (the IMAP/CalDAV connection getting closed by the server after ~10–30 minutes of inactivity) are handled inside the broker — the next verb call catches `imaplib.IMAP4.abort` / `requests.exceptions.ConnectionError`, re-LOGINs, and retries once. The state stays `running` throughout.

---

## Adding, editing, deleting

All UI actions live under **Settings → Integrations** in the app.

**Add** opens a modal flow: choose an integration → connect and verify it →
select individual tools → review. The connection is created with zero operation
grants before tool selection; cancelling the unfinished flow removes that
setup-owned connection. OAuth connections use the same post-connection tool
selection and review steps as app-password and token integrations.

Selections stay in local UI state until Review is finished. Explicit
cancellation deletes the setup-owned record; failed cleanup keeps the modal
open for retry. Closing the app or losing the page is not a server-side abort
and can leave a persisted zero-grant integration. Finishing Review with no
tools selected intentionally keeps that integration.

Forms are explicit frontend adapters, not fields rendered from backend catalog
schemas. Setup and reconnect reuse `ConnectionStep` and submission helpers;
setup and editing reuse `OperationPicker`. Reconnect replaces credentials on
the same ID, preserves grants, and never deletes the existing integration when
cancelled. OAuth cancellation is rejected while a supervisor commit is in
progress; completed new setup returns its ID for cleanup if cancellation wins
the UI race. Granted OAuth scopes limit offered operations, not automatically
enabled tools.

**Edit** uses a master-detail layout: list on the left, a read-only overview on
the right. The overview summarizes selected tools by group. **Change tools**
opens a focused dialog with the shared searchable tool picker; **Rename** opens
a separate name editor. Each dialog saves only its own fields, and Cancel
discards its draft. Label changes are metadata-only; grant changes apply to the
running broker after acknowledgement. Save is disabled until something differs
from the server state.

**Connection settings** starts collapsed and contains Rename and a service-specific
credential action: **Sign in again** for Google, **Update app password** for
iCloud/Gmail, or **Update token** for HTTP APIs. These reuse the existing
connection forms and preserve the integration ID and tool grants. HTTP updates
also require confirming the API connection details; credentials are not
prefilled from the vault.

**Remove integration** requires a second confirmation click. It stops the broker and its watcher,
removes the registry record, and deletes `.meta`, `.enc`, and any legacy metadata
backup. A stale socket pathname can remain after process exit; binding a new
broker removes the stale pathname before listening.

The wizard does **not** support renaming the connection ID after the fact — only the label.

---

## Files & locations

| Path | Owner | Mode | Purpose |
|---|---|---|---|
| `/var/lib/omnideck/vault/` | `broker:broker` | `0700` | Encrypted credential store + master key |
| `/var/lib/omnideck/vault/.master-key` | `broker:broker` | `0600` | AES-256 master key |
| `/var/lib/omnideck/vault/.migrations.json` | `broker:broker` | `0600` | Vault migration ledger |
| `/var/lib/omnideck/vault/creds/` | `broker:broker` | `0700` | Credential and metadata files |
| `/var/lib/omnideck/vault/creds/<id>.meta` | `broker:broker` | `0600` | Plaintext metadata (label, operation grants, slug) |
| `/var/lib/omnideck/vault/creds/<id>.enc` | `broker:broker` | `0600` | Encrypted credential blob |
| `/var/lib/omnideck/vault/creds/<id>.meta.pre-v3.bak` | `broker:broker` | `0600` | Original legacy metadata, if migrated |
| `/run/cvault/` | `broker:broker` | `0750` | Runtime sockets; not part of the persistent state volume |
| `/run/cvault/app.sock` | `broker:broker` | `0660` | Supervisor RPC; omnideck group can connect |
| `/run/cvault/<id>.sock` | `broker:broker` | `0660` | Per-broker verb dispatch socket |
| `/home/omnideck/downloads/` | `omnideck:broker` | `3770` | Shared browser downloads and broker-retrieved files |

The downloads directory uses setgid so new files inherit the broker group, and
the sticky bit prevents the broker from deleting files owned by omnideck.
omnideck, as directory owner, can remove either user's files. Broker attachment
files use mode `0640`, allowing the agent to read them.

---

## Troubleshooting

**Integration shows `auth failed` shortly after add.**
The credential was wrong, expired, or revoked. Use Reconnect from the
connection tab. App-password providers ask for a replacement password; OAuth
providers run authorization again.

**Integration shows `not running` (`broken` state).**
The broker could not start, exhausted crash recovery, or was stopped after an
uncertain control update or persistence failure. Check container logs for its ID;
common causes are blocked network egress, provider downtime, or TLS failure.
Reconnect after the underlying issue is resolved.

**Integrations tab shows "Integrations unavailable" with a Try again button.**
The aiohttp app can't reach the supervisor. The supervisor process probably crashed or isn't running. In dev mode (`DEV_MODE=true`), the entrypoint respawns it automatically; in prod mode the container will exit and Docker's restart policy takes over. If it persists, check `docker logs` for `[supervisor]` errors.

**The agent says it can't list emails but the UI shows `connected`.**
The broker reconnects automatically when the upstream server drops an idle connection. Check the container logs for `IMAP connection stale (...); reconnecting and retrying once` — if you see that line followed by a successful `IMAP LOGIN ok`, the broker recovered and the next agent call should work. If the reconnect itself fails, treat it as a real network or upstream issue (provider down, DNS / egress blocked).

---

## Security model

**What it defends against:**

- **Direct credential-file reads from the agent UID.** The agent (UID 1000)
  cannot open the vault directory (mode `0700`, owned by UID 1001), including
  `.master-key` and `.enc` files. The supervisor and broker processes hold
  decrypted credentials while preparing or serving connections.
- **An agent bypassing `broker_client` to connect directly to a broker's UDS.** The broker enforces exact operation grants at verb dispatch, before reaching upstream, regardless of which client called it.
- **Credentials leaking into argv.** Startup credentials use environment fields,
  never command-line arguments; live updates use inherited private pipes.
  Removing fields from `os.environ` does not erase the original `/proc`
  environment. Cross-UID process inspection restrictions remain essential.
- **Default-private new files.** The supervisor and brokers install `umask 0077` at startup (per `brokering/_perms.py`), so any file or directory they create without an explicit mode lands at owner-only by default. Sockets that genuinely need group access get an explicit `chmod 0660` after bind.
- **Credentials leaking via core dumps.** The supervisor and brokers call `setrlimit(RLIMIT_CORE, (0, 0))` at startup, so a crash can't write the process's memory to a core file where another UID might read it.
- **A malicious caller trying an ungranted broker verb.** The supervisor is the
  only process that spawns brokers, and the broker independently enforces the
  exact grants it received at spawn or through private control updates.

**What it does NOT defend against (explicit non-goals for v1):**

- **Agent access to management RPC.** The app server and agent share the
  omnideck UID and broker-group access to `app.sock`. There is no trusted-UI
  caller identity preventing agent-executed code from requesting grant changes.
  Per-broker dispatch enforces the current grants, but this management-plane
  authorization gap is explicitly deferred, not solved by private child pipes.
- **Container breakout.** If an attacker escapes the container as root or breaks the UID 1000/1001 boundary, all bets are off.
- **Backup theft.** The state volume contains both the master key and the encrypted blobs. Treat backups like a password-manager export.
- **`ptrace`-based memory inspection.** v1 doesn't assert `kernel.yama.ptrace_scope >= 1` at startup or refuse to run with `CAP_SYS_PTRACE`. The kernel default already blocks the realistic cross-UID attack (agent UID can't ptrace broker UID without `CAP_SYS_PTRACE`), but if the container is launched with that capability granted, an in-container same-UID-as-broker attacker could attach a debugger and read the credential. Asserting these flags at startup is a follow-up item.
- **An MCP server (when MCP lands) abusing creds it was given.** Mitigation is "user consented by installing it." Per-integration egress allowlists are a future hardening item.
- **Disk-level forensic recovery.** Deleted credentials are unlinked, not
  securely erased; interrupted atomic writes may leave temporary files.

---

## Code map

| Component | Path |
|---|---|
| Supervisor (vault, lifecycle, RPC) | `brokering/supervisor/` |
| Email broker (IMAP + SMTP + CalDAV) | `brokering/brokers/email_broker/` |
| Wire framing + ready signal + exit codes | `brokering/_rpc.py`, `brokering/_ready.py`, `brokering/_exit_codes.py` |
| Tool-integration catalog | `integrations/catalog/` |
| Model-provider presets and HTTP proxy | `brokering/brokers/llm_proxy/` |
| Combined process catalog and validation | `brokering/catalog.py` |
| Broker launch contracts | `brokering/drivers.py` |
| Canonical operation registry | `integrations/operations.py` |
| Application/SDK boundary | `integrations/service.py` |
| Application discovery cache | `integrations/connection_cache.py` |
| Vault migration plan | `brokering/migrations/` |
| Broker session ownership and private control | `brokering/_session_slot.py`, `brokering/_control.py` |
| Shared integration broker runtime | `brokering/brokers/_common/_runtime.py` |
| App-server HTTP/OAuth routes | `server/_integrations_routes.py`, `server/_integrations_oauth_routes.py` |
| Agent-side broker client | `brokering/broker_client/` |
| Agent tool wrappers | `tools/integrations/` |
| React UI | `server/ui/src/features/integrations/` |

`integrations` owns tool presets, operations, grants, the application service,
and the connection discovery cache.
`brokering` owns credential storage, process lifecycle, transport clients, and
all concrete brokers under `brokering.brokers`, including the separate LLM HTTP
proxy. Model adapters remain in `agent_core.providers`,
with configured provider selection in `providers`; LLM requests do not use
integration operations or the HTTP API broker.

`brokering.catalog` is the composition boundary that combines the two preset
catalogs and validates them before startup. The supervisor still applies the
existing integration/model-provider connection policies; it is not a generic
plugin framework. Transport primitives and the LLM proxy do not import tool
integrations. Server route families share `server/_brokering.py` for connection
management. Persisted metadata, connection IDs, vault/socket paths, and config
keys are unchanged by the package split; legacy permission metadata is upgraded
by the vault migration described above. Connection listings use the single `connections` field;
internal Python import paths and connection type names have changed.

Isolated tests live under `tests/unit/brokering/`, `tests/unit/integrations/`,
`tests/unit/tools/integrations/`, and `tests/unit/server/`. Tests exercising
real HTTP/Unix sockets, broker subprocesses, OAuth token exchange, and vault
lifecycle live under `tests/integration/brokering/` and
`tests/integration/integrations/`; run both with `just integration`.
Browser setup/edit/recovery tests live under `tests/e2e/settings/` and run
through `just e2e`. See the [integration test guide](../tests/integration/integrations/README.md)
for the boundaries and local fake services.

For credential-free manual testing, set `OMNIDECK_ENABLE_TEST_INTEGRATIONS=1`
in the container environment before starting the app and supervisor. This adds
the development-only Test integration; use `omnideck-test-token` for successful
authentication (any other token is rejected). Its two operations, `test.value.get`
and `test.value.set`, exercise independent grants and broker state without an
external service. It is absent from the default catalog and has no LLM tool
adapter; operation invocation is covered through broker RPC in integration/E2E
tests. Do not enable it in a production deployment.

---

See [`plans/integrations-followups.md`](../plans/integrations-followups.md) for what's next.
