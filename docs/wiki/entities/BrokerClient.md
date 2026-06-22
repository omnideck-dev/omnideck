---
title: BrokerClient
type: entity
tags: [integrations, broker, client, rpc, unix-socket]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Integrations Overview]]"]
---

# BrokerClient

## Overview

`BrokerClient` (in `integrations/broker_client/`) is the public client used by app-server code and tool handlers to call integration broker verbs. It abstracts the RPC transport (Unix Domain Socket) and translates error codes into typed Python exceptions.

## Details

**Primary API:** `integrations.broker_client.call(integration_id, verb, args, app_sock_path=...)`
- Routes the call through the supervisor at `app_sock_path`
- The supervisor proxies to the appropriate broker's UDS

**Error types:**
- `IntegrationError` — generic integration error
- `IntegrationAuthFailed` — authentication failure (e.g., expired OAuth token)
- `IntegrationNotConnected` — broker not running or supervisor unreachable
- `IntegrationPermissionDenied` — permission check failed
- `IntegrationWriteDenied` — write operation blocked by policy

**Usage pattern:**
```python
from integrations import broker_client
result = await broker_client.call("gmail_personal", "list_mailboxes", {})
```

**Tool handlers** import from `integrations` (which re-exports `broker_client`) to avoid direct sub-package imports.

## Related Entities

- [[IntegrationSupervisor]] (the process being called)
- [[SupervisorClient]] (for supervisor-level operations)
- [[AnthropicProvider]] (uses UDS transport for LLM proxying)

## Sources

- [[Source - Integrations Overview]]
