# Integrations

## What an integration is

An *integration* is a credentialed connection to an external service. Each
connection has an explicit set of canonical operations, and the user chooses
which of those operations omnideck may expose as agent tools.

| Provider | Operations | Auth |
|---|---|---|
| iCloud | Email (IMAP + SMTP) + Calendar (CalDAV) | App-specific password |
| Gmail | Email (IMAP + SMTP) | App-specific password |
| Google Workspace | Gmail, Calendar, Drive, Contacts | Desktop OAuth |
| Custom HTTP API | One authenticated HTTP request operation | Static token |

Each integration becomes one or more agent tools — `list_email_messages`, `move_email`, `send_email`, `list_calendars`, `list_events`, etc. The tools take an explicit `integration_id` argument (e.g. `"icloud_personal"` or `"gmail_work"`), so the agent picks which account to operate on per call.

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
- One **broker subprocess per integration**. Brokers are independent processes that hold the decrypted credential in their own memory and connect directly to the upstream provider (Gmail's IMAP, iCloud's CalDAV, etc.).
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

The agent never has read access to a credential — its UID can't open the vault, and brokers wipe the credential out of `os.environ` after reading it into the IMAP/SMTP/CalDAV client objects.

---

## Operation grants

Every callable integration action has a stable canonical operation ID, such
as `email.messages.search`, `calendar.events.create`, or `http.request`. A
connection stores the exact operation IDs granted to the agent; new
connections begin with no grants until setup reaches the tool-selection step.

Two layers apply the same policy:

1. **Broker-side gate (the security boundary).** The supervisor passes the
   exact operation grants to the broker at spawn. The shared broker dispatcher
   accepts canonical operation IDs directly in the RPC `verb` field and returns
   `PERMISSION_DENIED` unless that ID is granted. This applies even to a caller
   that reaches a broker socket directly.
2. **App-server projection (tool discovery).** Agent tool adapters are built
   only for granted operations on running connections. This keeps unavailable
   operations out of the model's tool list; it does not replace the broker gate.

Changing grants respawns the broker so the new immutable process environment
takes effect. Legacy capability/read-write fields remain only at migration and
older-client compatibility boundaries; runtime authorization does not use them.

---

## How credentials are stored

Per-integration files in the vault directory:

```
/var/lib/omnideck/vault/
├── master.key                        # 32-byte AES-256 key, mode 0600
├── icloud_personal.meta              # plaintext JSON: id, slug, label, operation grants, timestamps
├── icloud_personal.enc               # AES-256-GCM(plaintext_blob, key=master, aad=integration_id)
├── gmail_work.meta
└── gmail_work.enc
```

The plaintext blob is a JSON object the auth plugin defines — for `app_password`, it's `{"email": "...", "password": "..."}`. The supervisor decrypts it at broker spawn time and passes the relevant fields as env vars (`IMAP_USER`, `IMAP_PASS`, etc.); the broker reads them into client objects on its first IMAP/CalDAV connect, then `os.environ.pop()`s the password.

**Encryption details:**

- AES-256-GCM. Random 12-byte nonce per blob, prepended to the ciphertext.
- AAD = the integration ID, so re-using a stale blob under a different name would fail to decrypt.
- A version byte at the start (`0x01`) reserves room for future format changes.
- The master key is a 32-byte CSPRNG output, written once to `master.key` on first supervisor boot. **It does not rotate** in v1 — see [follow-ups](../plans/integrations-followups.md) for the planned rotation command.

The master key is on local disk at mode `0600 broker:broker`. If an attacker can read that file *and* the `.enc` blobs, they have your credentials. Treat the `/var/lib/omnideck/vault/` volume the same way you'd treat a password-manager backup.

---

## State machine

Each integration has a state visible in the UI. Transitions are driven by broker process events (the supervisor watches `proc.wait()` exit codes) and user actions.

| State | Meaning | UI affordance |
|---|---|---|
| `running` | Broker up, upstream auth ok | Green dot, label `connected` |
| `auth_failed` | Broker exited with code 77 — upstream rejected the credential | Red status and reconnect action |
| `broken` | Broker exited non-77 three times in a row before READY | Red status and reconnect action |

Auto-restart policy:

- **`auth_failed`** is sticky. The supervisor stops respawning. Recovery uses
  reconnect, which atomically verifies and replaces credentials while retaining
  grants that are still available under the new authorization.
- **Generic crashes** (anything except exit 77) trigger exponential backoff respawn: 1s → 2s → 4s → 8s → 16s, capped at 30s. After three consecutive failures the integration flips to `broken` and respawn stops.
- **Idle drops** (the IMAP/CalDAV connection getting closed by the server after ~10–30 minutes of inactivity) are handled inside the broker — the next verb call catches `imaplib.IMAP4.abort` / `requests.exceptions.ConnectionError`, re-LOGINs, and retries once. The state stays `running` throughout.

---

## Adding, editing, deleting

All UI actions live under **Settings → Integrations** in the app.

**Add** opens a modal flow: choose an integration → connect and verify it →
select individual tools → review. The connection is created with zero operation
grants before tool selection; cancelling the unfinished flow removes that
setup-owned connection. OAuth connections use the same post-connection tool
selection and review steps as app-password and token integrations.

**Edit** uses a master-detail layout: list on the left, detail pane on the
right. The Overview, Tools, and Connection tabs separate metadata, exact agent
tool grants, and credential recovery. Label changes are metadata-only; grant
changes respawn the broker. Save is disabled until something differs from the
server state.

**Delete** is one-click + browser confirm. Removes both `.meta` and `.enc`, SIGTERMs the broker, and deletes the per-broker socket file.

The wizard does **not** support renaming the integration ID after the fact — only the label.

---

## Files & locations

| Path | Owner | Mode | Purpose |
|---|---|---|---|
| `/var/lib/omnideck/vault/` | `broker:broker` | `0700` | Encrypted credential store + master key |
| `/var/lib/omnideck/vault/master.key` | `broker:broker` | `0600` | AES-256 master key |
| `/var/lib/omnideck/vault/<id>.meta` | `broker:broker` | `0640` | Plaintext metadata (label, operation grants, slug) |
| `/var/lib/omnideck/vault/<id>.enc` | `broker:broker` | `0640` | Encrypted credential blob |
| `/run/cvault/` | `broker:broker` | `0750` | tmpfs — runtime sockets |
| `/run/cvault/app.sock` | `broker:broker` | `0660` | Supervisor RPC; omnideck group can connect |
| `/run/cvault/<id>.sock` | `broker:broker` | `0660` | Per-broker verb dispatch socket |
| `/run/cvault/attachments/` | `broker:broker` | `2770` | Side channel for fetched email attachments |

The `attachments/` directory uses setgid + sticky bits so both `broker` (writer) and `omnideck` (reader, downloads dir owner) can play nice without either being able to delete the other's files.

---

## Troubleshooting

**Integration shows `auth failed` shortly after add.**
The credential was wrong, expired, or revoked. Use Reconnect from the
connection tab. App-password providers ask for a replacement password; OAuth
providers run authorization again.

**Integration shows `not running` (`broken` state).**
The broker crashed three times in a row before completing its initial
handshake. Check `docker logs <container>` for the broker's connection ID;
common causes are blocked network egress, provider downtime, or TLS failure.
Reconnect after the underlying issue is resolved.

**Integrations tab shows "Integrations unavailable" with a Try again button.**
The aiohttp app can't reach the supervisor. The supervisor process probably crashed or isn't running. In dev mode (`DEV_MODE=true`), the entrypoint respawns it automatically; in prod mode the container will exit and Docker's restart policy takes over. If it persists, check `docker logs` for `[supervisor]` errors.

**The agent says it can't list emails but the UI shows `connected`.**
The broker reconnects automatically when the upstream server drops an idle connection. Check the container logs for `IMAP connection stale (...); reconnecting and retrying once` — if you see that line followed by a successful `IMAP LOGIN ok`, the broker recovered and the next agent call should work. If the reconnect itself fails, treat it as a real network or upstream issue (provider down, DNS / egress blocked).

---

## Security model

**What it defends against:**

- **Agent prompt-injection or runaway tool calls reading credentials.** The agent (UID 1000) cannot open the vault directory (mode `0700`, owned by UID 1001). Even an agent with `bash-run` cannot read `master.key` or any `.enc` blob. The credential only exists in plaintext in the broker process's memory.
- **An agent bypassing `broker_client` to connect directly to a broker's UDS.** The broker enforces exact operation grants at verb dispatch, before reaching upstream, regardless of which client called it.
- **Credentials leaking into argv.** Credentials are passed via env, never argv. The broker `os.environ.pop("EMAIL_PASS", None)`s the password into client-object state immediately after reading it, so a `cat /proc/<pid>/environ` from another UID won't find it.
- **Default-private new files.** The supervisor and brokers install `umask 0077` at startup (per `integrations/_perms.py`), so any file or directory they create without an explicit mode lands at owner-only by default. Sockets that genuinely need group access get an explicit `chmod 0660` after bind.
- **Credentials leaking via core dumps.** The supervisor and brokers call `setrlimit(RLIMIT_CORE, (0, 0))` at startup, so a crash can't write the process's memory to a core file where another UID might read it.
- **A malicious caller trying an ungranted broker verb.** The supervisor is the
  only process that spawns brokers, and the broker independently enforces the
  exact grants it received at spawn.

**What it does NOT defend against (explicit non-goals for v1):**

- **Container breakout.** If an attacker escapes the container as root or breaks the UID 1000/1001 boundary, all bets are off.
- **Backup theft.** The state volume contains both the master key and the encrypted blobs. Treat backups like a password-manager export.
- **`ptrace`-based memory inspection.** v1 doesn't assert `kernel.yama.ptrace_scope >= 1` at startup or refuse to run with `CAP_SYS_PTRACE`. The kernel default already blocks the realistic cross-UID attack (agent UID can't ptrace broker UID without `CAP_SYS_PTRACE`), but if the container is launched with that capability granted, an in-container same-UID-as-broker attacker could attach a debugger and read the credential. Asserting these flags at startup is a follow-up item.
- **An MCP server (when MCP lands) abusing creds it was given.** Mitigation is "user consented by installing it." Per-integration egress allowlists are a future hardening item.
- **Disk-level forensic recovery.** We don't shred old `.enc.tmp` files, just `unlink()` them.

---

## Code map

| Component | Path |
|---|---|
| Supervisor (vault, lifecycle, RPC) | `integrations/supervisor/` |
| Email broker (IMAP + SMTP + CalDAV) | `integrations/brokers/email_broker/` |
| Wire framing + ready signal + exit codes | `integrations/_rpc.py`, `integrations/brokers/_common/` |
| Integration and model-provider catalogs | `integrations/catalog/` |
| Broker launch contracts | `integrations/drivers.py` |
| Canonical operation registry | `integrations/operations.py` |
| Application/SDK boundary | `integrations/service.py` |
| App-server HTTP routes | `server/_integrations_routes.py` |
| Agent-side broker client | `integrations/broker_client/` |
| Agent tool wrappers | `tools/integrations/` |
| React UI | `server/ui/src/features/integrations/` |

The catalog package owns preset types, built-in definitions, and validation.
It depends on the shared driver contracts and operation registry, not on the
supervisor. Server routes and the supervisor consume its public API; the
supervisor remains responsible for connection state, credentials, and processes.

Isolated tests live under `tests/unit/integrations/`,
`tests/unit/tools/integrations/`, and `tests/unit/server/`. Tests exercising
real HTTP/Unix sockets, broker subprocesses, OAuth token exchange, and vault
lifecycle live under `tests/integration/integrations/`; run them with
`uv run pytest tests/integration/integrations/` or as part of `just integration`.
Browser setup/edit/recovery tests live under `tests/e2e/settings/` and run
through `just e2e`. See the [integration test guide](../tests/integration/integrations/README.md)
for the boundaries and local fake services.

---

See [`plans/integrations-followups.md`](../plans/integrations-followups.md) for what's next.
