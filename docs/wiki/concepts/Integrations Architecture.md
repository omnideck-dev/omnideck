---
title: Integrations Architecture
type: concept
tags: [integrations, security, broker, supervisor, vault]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "integrations/"
  - "tools/integrations/"
  - "server/_integrations_routes.py"
---

# Integrations Architecture

## Overview

Integrations connect the agent to external services (currently Gmail and iCloud email/calendar). Each integration runs as an isolated broker subprocess under a separate OS user (`broker`, UID 1001), preventing the agent process (`computron`, UID 1000) from accessing credentials directly. The aiohttp app and agent tools communicate with brokers over Unix Domain Sockets.

## Process Model

```
computron (UID 1000)          broker (UID 1001)
────────────────────          ─────────────────
aiohttp app                   supervisor
  HTTP routes ─────────────►    (vault, spawn, RPC dispatch)
  agent tools ─────────────►    ├── email_broker[gmail]
    via /run/cvault/              │     └── IMAP/SMTP → gmail
    <id>.sock                     └── email_broker[icloud]
                                        └── IMAP/SMTP/CalDAV → icloud
```

Three OS users exist: `root` (container init only, drops via gosu), `broker` (supervisor + all brokers + vault), `computron` (app + agent). `computron` is in the `broker` group and can connect to broker sockets but cannot read the vault directory (`0700 broker:broker`).

## Components

### Supervisor (`integrations/supervisor/`)

Long-lived process owning:
- The encrypted credential vault at `/var/lib/computron/vault/`
- Lifecycle management for broker subprocesses (spawn, respawn with exponential backoff, SIGTERM on delete)
- The `app.sock` UDS at `/run/cvault/app.sock` — receives CRUD operations from the aiohttp app
- Integration state machine (pending → running / auth_failed / broken)

### Brokers (`integrations/brokers/`)

Short-lived per-integration processes that:
- Receive credentials as env vars at spawn, then `os.environ.pop()` them into client state
- Bind a per-broker UDS at `/run/cvault/<id>.sock`
- Execute verb calls (e.g., `list_mailboxes`, `send_email`) on behalf of agent tools
- Enforce `WRITE_ALLOWED` gate — write verbs are refused locally when the flag is false
- Handle idle reconnection: catch stale IMAP connection, re-LOGIN, retry once

### Credential Vault

AES-256-GCM encrypted files per integration:
- `<id>.meta` — plaintext JSON: id, slug, label, `write_allowed`, timestamps
- `<id>.enc` — encrypted credential blob (email + password)
- `master.key` — 32-byte key, written once at first supervisor boot, not rotated in v1

The supervisor decrypts at broker spawn time and passes fields as env vars.

### Broker Client (`integrations/broker_client/`)

Called by agent tools to invoke broker verbs:
```python
from integrations import broker_client
result = await broker_client.call("gmail_personal", "list_mailboxes", {}, app_sock_path=...)
```
Short-circuits denied writes with `IntegrationWriteDenied` before a socket round-trip.

### Agent Tool Wrappers (`tools/integrations/`)

One file per tool: `list_email_messages.py`, `send_email.py`, `list_events.py`, etc. Each tool:
- Takes an explicit `integration_id` argument so the agent picks which account to use
- Calls `broker_client.call()` with the appropriate verb
- Formats the response for human-readable LLM consumption

## Permissions Model

Two-layer write enforcement:
1. **Broker-side (real security boundary):** supervisor passes `WRITE_ALLOWED` env var at spawn; broker refuses write verbs locally regardless of who called it
2. **App-server-side (UX):** write tools are hidden from the agent's tool registry when `write_allowed=false`

Toggling `write_allowed` triggers broker respawn (1–3 seconds of downtime).

## Integration State Machine

`pending` → `running` (happy path)
`pending` → `auth_failed` (exit code 77 — bad credential, sticky, no respawn)
`pending` / `running` → `broken` (3 consecutive non-77 crashes, respawn stops)

Exponential backoff for generic crashes: 1s → 2s → 4s → 8s → 16s, capped at 30s.

## Where It Lives

| Path | Role |
|------|------|
| `integrations/supervisor/` | Supervisor process and vault |
| `integrations/brokers/` | Broker subprocess implementations |
| `integrations/broker_client/` | App-side broker call helper |
| `integrations/supervisor_client/` | App-side supervisor management calls |
| `integrations/_rpc.py` | Wire framing (length-prefixed frames over UDS) |
| `integrations/_perms.py` | `umask`, `setrlimit` security setup |
| `tools/integrations/` | Agent tool wrappers |
| `server/_integrations_routes.py` | HTTP routes for integration CRUD |
| `server/_integrations_oauth_routes.py` | OAuth flow routes (for providers that need it) |
| `server/ui/src/components/integrations/` | React UI for Integrations settings |

## Open Questions

- Master key rotation is not implemented in v1 (noted in `plans/integrations-followups.md`).
- MCP server support is planned; per-integration egress allowlists are a future hardening item.

## Sources

- `docs/integrations.md` — full architecture spec with security analysis
