---
title: IntegrationSupervisor
type: entity
tags: [integrations, supervisor, security, credentials, unix-socket]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Integrations Overview]]"]
---

# IntegrationSupervisor

## Overview

The Integration Supervisor (in `integrations/supervisor/`) is the credential-owning trusted process that runs as a dedicated UID and holds the master key for the credential vault. It spawns and manages broker sub-processes for each integration and mediates all credential-bearing operations. The app server never receives decrypted credentials.

## Details

**Security model:**
- Runs as dedicated UID separate from the app server user
- Holds master key for credential vault (encrypted API keys, OAuth tokens)
- App server communicates via Unix Domain Socket at `config.integrations.app_sock_path` (default: `/run/cvault/app.sock`)
- Each broker's UDS socket lives in `config.integrations.sockets_dir` (default: `/run/cvault/`)

**Broker management:**
- Spawns broker sub-processes for registered integrations (Gmail, Calendar, Drive, etc.)
- Brokers complete a READY handshake with the supervisor after startup
- LLM provider keys also brokered: `llm_{provider}.sock` (e.g., `llm_anthropic.sock`)

**App startup integration:**
- App server waits up to 30s for integrations readiness signal
- If supervisor is unreachable, chat still works but integration tools are unavailable
- `tools/integrations.registered_integrations()` and `cache_loaded()` expose readiness to the app factory

**RPC protocol:** shared framing in `integrations/brokers/_common/_rpc.py` (internal, not re-exported)

**Permissions:** `integrations/permissions.py` and `_perms.py` provide per-integration permission checks

## Related Entities

- [[BrokerClient]] (how app code talks to integrations)
- [[SupervisorClient]] (how app code talks to supervisor)
- [[AnthropicProvider]] (uses proxy socket)
- [[OpenAIProvider]] (uses proxy socket)
- [[AppConfig]] (`integrations` section)

## Sources

- [[Source - Integrations Overview]]
