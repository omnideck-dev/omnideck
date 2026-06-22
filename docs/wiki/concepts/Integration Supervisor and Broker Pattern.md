---
title: Integration Supervisor and Broker Pattern
type: concept
tags: [integrations, supervisor, broker, credentials, security, unix-socket]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Integrations Overview]]"]
---

# Integration Supervisor and Broker Pattern

## Overview

The Integration Supervisor and Broker Pattern is Omnideck's security architecture for managing credentials. A privilege-separated supervisor process owns the credential vault; the app server (and thus the LLM agent) never sees decrypted API keys or OAuth tokens. All credential-bearing operations go through the supervisor via Unix Domain Sockets.

## How It Works

```
App Server (computron user)
    │
    │  integrations.broker_client.call("gmail_personal", "list_mailboxes", {})
    │
    ▼
Supervisor (dedicated UID, has vault master key)
    │  /run/cvault/app.sock
    │
    ├─ Gmail Broker (subprocess, decrypted Gmail OAuth token in memory)
    │    │  /run/cvault/gmail_personal.sock
    │    └─ Gmail API
    │
    ├─ Calendar Broker (subprocess, decrypted Calendar token)
    │    └─ Calendar API
    │
    └─ LLM Proxy Broker (e.g., llm_anthropic.sock)
         └─ Anthropic API (with API key from vault)
```

**Startup handshake:**
1. Supervisor starts, loads vault, spawns configured brokers
2. Each broker completes a READY handshake with supervisor
3. App server waits up to 30s for `integrations_ready` signal (via `registered_integrations()`)
4. If deadline expires, app continues without integration tools (graceful degradation)

**LLM provider brokering:**
- Cloud LLM providers (Anthropic, OpenAI) are brokered the same way as data integrations
- Provider SDK traffic is routed via `httpx.AsyncHTTPTransport(uds=proxy_socket_path)`
- The broker adds the API key to outgoing requests; app server sent request with `api_key="proxy"`

**Tool handler flow:**
```python
from integrations import broker_client
result = await broker_client.call("gmail_personal", "list_mailboxes", {})
```

**Error propagation:** `IntegrationNotConnected` / `IntegrationAuthFailed` / `IntegrationPermissionDenied` etc. provide actionable error types for the tool handler to surface to the agent.

## Key Details

- App server never has the vault master key → credential isolation even if app code is compromised
- UDS sockets (`/run/cvault/`) are only accessible to the supervisor and app server user
- OAuth flow: the app server handles redirect/callback via `_integrations_oauth_routes.py` but tokens are stored in the vault by the supervisor
- Readiness deadline (30s) is generous — covers cold starts with multiple IMAP/CalDAV logins

## Open Questions

- What is the full list of supported integrations (brokers)? Confirmed: Gmail, Calendar, Drive. Others referenced but not confirmed.
- What vault encryption mechanism is used? Not exposed in public API.

## Sources

- [[Source - Integrations Overview]]
