---
title: "Source - Integrations Overview"
type: source
tags: [integrations, supervisor, broker, oauth, gmail, calendar, drive]
created: 2026-06-22
updated: 2026-06-22
sources: []
---

# Source - Integrations Overview

## Summary

The `integrations/` package implements a privilege-separated integration architecture. The `supervisor/` runs as a dedicated UID and owns the credential vault (master key), spawning broker sub-processes for each integration (Gmail, Calendar, Drive, etc.). App-server code and tools communicate with the supervisor over a Unix Domain Socket and with individual brokers via their own UDS sockets. This means the app server (running as the agent user) never sees decrypted credentials. LLM providers are also brokered through this system (via `llm_{provider}.sock`).

## Key Points

**Supervisor (`integrations/supervisor/`):**
- Dedicated UID that holds the master key for the credential vault
- Spawns and manages broker sub-processes
- Brokers register with a READY handshake
- App server communicates via `app.sock` (configured in `config.integrations.app_sock_path`)

**Broker client (`integrations/broker_client/`):**
- `call(integration_id, verb, args, app_sock_path=...)` — sends RPC to a specific broker via the supervisor
- Error types: `IntegrationAuthFailed`, `IntegrationError`, `IntegrationNotConnected`, `IntegrationPermissionDenied`, `IntegrationWriteDenied`
- Brokered LLM providers also route through this: socket at `{sockets_dir}/llm_{provider}.sock`

**Supervisor client (`integrations/supervisor_client/`):**
- Client for app-server → supervisor communication
- Used for adding/listing/removing integrations without exposing credentials to app server

**Broker sub-processes (`integrations/brokers/`):**
- External service integrations: Gmail, Calendar, Drive, etc.
- Each runs as a subprocess, communicates via UDS
- Shared RPC framing in `_common/_rpc.py`

**Permissions (`integrations/permissions.py`, `_perms.py`):**
- Per-integration permission checks

**OAuth (`server/_integrations_oauth_routes.py`, `integrations/_oauth.py`):**
- OAuth flow for brokered cloud providers
- Routes: `register_oauth_routes(app)`

## Entities Mentioned

- [[IntegrationSupervisor]]
- [[BrokerClient]]
- [[SupervisorClient]]
- [[AnthropicProvider]]
- [[OpenAIProvider]]

## Concepts Covered

- [[Integration Supervisor and Broker Pattern]]
- [[Provider Abstraction]]

## Raw Notes

- App server never reads decrypted credentials — supervisor is the only process with the vault key
- Integrations readiness signal has a 30s deadline on startup; if supervisor is unreachable, chat still works but without integration tools
- `sockets_dir` default: `/run/cvault` — UDS sockets for all brokers live here
- `tools/integrations/` (not the same as `integrations/`) exposes `registered_integrations()` and `cache_loaded()` for the app factory's readiness check
