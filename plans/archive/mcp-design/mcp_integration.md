# MCP integrations — architecture direction (RFC)

**Status:** Initial design for team discussion. This is not an execution plan and does not add MCP support by itself.

**Protocol baseline:** MCP `2026-07-28`, with compatibility for the handshake-era protocol through `2025-11-25` delegated to the official Python SDK. Revisit this baseline when implementation starts.

**Supersedes:** The MCP section of [`plans/integrations-followups.md`](integrations-followups.md). That section assumed a stdio-first relay, an `initialize` handshake, JSON-RPC ID rewriting, and an empty `tools/list` response as an authentication failure. Those assumptions no longer fit either the current protocol or OmniDeck's current code.

**Prerequisite:** [`plans/integration_core_refactor.md`](integration_core_refactor.md)
is the accepted integration model. MCP builds on canonical integration
operations and explicit per-consumer operation allowlists; it does not add a
new capability or read/write permission tier.

## 1. Decision summary

Build one reusable `mcp_broker` implementation and run one isolated instance of it per configured MCP integration, matching the existing broker lifecycle:

```text
one implementation                         many isolated instances

integrations/brokers/mcp_broker/           mcp_github_personal.sock
                                             mcp_linear_work.sock
                                             mcp_home_assistant.sock
```

The initial product should support **remote Streamable HTTP MCP servers**, with **OAuth as a complete first-class connection flow** rather than a token textbox bolted on afterward. It should expose upstream MCP tools as real model tools with their original JSON Schemas, loaded progressively per integration so connecting several large MCP servers does not put every tool in every model request.

Local stdio servers are deliberately deferred. Under the current process model, a child launched by an MCP broker would run as the shared `broker` UID and could read the entire integration vault, not only the credential intended for that server. Stdio support requires a separate sandbox design before it is safe to ship.

The main architectural choices are:

1. **Use the official `mcp` Python SDK, pinned to a reviewed 2.x range.** Do not build a JSON-RPC/MCP compatibility layer in OmniDeck. The SDK owns protocol-version negotiation, modern Streamable HTTP headers, legacy sessions, `x-mcp-header`, pagination, cancellation, and OAuth wire details.
2. **Keep OmniDeck's UDS protocol semantic.** The app calls broker verbs such as `list_tools` and `call_tool`; it does not relay raw MCP frames. The broker is the MCP client.
3. **Generalize OAuth below the provider UI.** Discovery, PKCE, client registration, token exchange, refresh, rotation persistence, issuer binding, resource indicators, and step-up authorization belong in a reusable integration OAuth subsystem. The current Google-only flow can migrate to it later.
4. **Project discovered MCP tools into canonical integration operations.** MCP tool schemas cannot be faithfully squeezed through today's Python-signature-only agent-tool abstraction, especially now that MCP accepts full JSON Schema 2020-12. The integration-operation layer retains the upstream schema; the agent-tool layer is one consumer projection over it.
5. **Use an explicit operation allowlist.** Every newly discovered MCP operation is denied until the user selects it. Tool annotations remain untrusted, descriptive hints and never grant access. OAuth scope minimization is a separate, stronger remote-authorization boundary.

## 2. Goals and non-goals

### Goals

- A user can connect many remote MCP servers through one generic integration type.
- OAuth-protected servers feel like a normal sign-in flow: paste an MCP URL, review access, authorize in the browser, return connected.
- Unauthenticated remote servers work through the same flow without fake credentials.
- Curated presets can supply an endpoint, name, icon, and optional pre-registered OAuth client information without requiring a new broker implementation.
- Each MCP integration has isolated lifecycle, credentials, operation grants, failures, and tool namespace.
- MCP tools retain their upstream input schemas and useful result content.
- Tool catalogs are loaded on demand and refreshed without restarting OmniDeck.
- Existing email, calendar, Drive, Contacts, and HTTP integrations, plus brokered LLM providers, keep their current behavior through the core migration.

### Non-goals for the first release

- Local stdio MCP servers or arbitrary `uvx` / `npx` command execution.
- Legacy HTTP+SSE as a user-selectable transport. Compatibility may come from the SDK when it is safe and automatic, but the UI should not encourage a deprecated transport.
- MCP prompts, resource browsing, roots, sampling, protocol logging, MCP Apps, or Tasks.
- Automatic execution of MCP elicitation / multi-round-trip input requests. The first release should return a clear `INTERACTION_REQUIRED` result and never silently answer on the user's behalf.
- A hosted MCP registry or marketplace.
- Claiming that broker-side operation selection contains a malicious MCP server.

## 3. Why this fits the current OmniDeck architecture

The existing split remains valuable:

- The app and agent run as `omnideck` and cannot read the vault.
- The supervisor owns encrypted credential persistence and broker lifecycle.
- A per-integration broker owns upstream connectivity and enforces the exact operation allowlist before a request leaves OmniDeck.
- Agent-facing tools are assembled through Skills and rebuilt on each turn.

MCP differs from the existing integrations in three ways:

1. The set of tools and their schemas is dynamic per connection.
2. OAuth is discovered from the resource rather than fully hardcoded by provider.
3. Tool results can contain structured data and multiple content types.

Those differences call for extensions to the tool and integration models, not a parallel integration stack.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ app / agent (UID omnideck)                                                   │
│                                                                              │
│  Settings UI ──► MCP connect + OAuth routes ──► supervisor app.sock          │
│  runtime Skill ─► McpRuntimeTool ─────────────► broker_client                │
└──────────────────────────────────────────────────────┬───────────────────────┘
                                                       │ UDS
┌──────────────────────────────────────────────────────▼───────────────────────┐
│ integration boundary (UID broker)                                           │
│                                                                              │
│  supervisor                                                                 │
│   ├─ encrypted vault                                                        │
│   ├─ OAuth transaction + rotated-token persistence                          │
│   └─ one process per connection                                             │
│       ├─ mcp_broker[github_personal] ── HTTPS ──► GitHub MCP                 │
│       ├─ mcp_broker[linear_work] ────── HTTPS ──► Linear MCP                 │
│       └─ mcp_broker[home] ───────────── HTTPS ──► Home Assistant MCP         │
└──────────────────────────────────────────────────────────────────────────────┘
```

This is one **broker driver**, not one process holding every MCP credential. Per-integration processes preserve the current crash, grant, credential, and observability boundaries. Brokered LLM providers reuse the same lower-level supervisor/vault/process platform but remain a separate `model_provider` domain; they do not expose integration operations.

## 4. Product model: generic connection plus optional presets

The source of truth should be a generic MCP connection:

```text
type: mcp
label: GitHub · personal
transport: streamable_http
endpoint: https://api.githubcopilot.com/mcp/
auth: discovered
```

A curated provider is only a preset over that model:

```text
title: GitHub
broker_kind: mcp
endpoint: <known endpoint>
icon: github
oauth_registration: <optional pre-registered client metadata>
```

This distinction prevents every MCP server from becoming Python code or a bespoke catalog schema. The generic Add flow accepts a URL; presets improve discoverability and reduce typing.

### Persisted configuration

`IntegrationMeta` needs a versioned, non-secret configuration field. Endpoint and transport do not belong in the encrypted credential blob merely because today's catalog can only inject static configuration or secrets.

Proposed shape, illustrative rather than final Pydantic syntax:

```json
{
  "version": 3,
  "id": "mcp_github_personal",
  "slug": "mcp",
  "broker_kind": "mcp",
  "label": "GitHub · personal",
  "config": {
    "transport": "streamable_http",
    "endpoint": "https://example.com/mcp",
    "network_policy": "public_https"
  },
  "agent_operation_grants": [
    "mcp:search",
    "mcp:get_issue"
  ],
  "added_at": "...",
  "updated_at": "..."
}
```

The encrypted blob contains only credential and registration state:

```json
{
  "auth_kind": "oauth",
  "issuer": "https://auth.example.com",
  "client_id": "...",
  "client_secret": "... only when applicable ...",
  "access_token": "...",
  "refresh_token": "... when issued ...",
  "expires_at": 1780000000,
  "scopes": ["files:read"],
  "resource": "https://example.com/mcp"
}
```

Registration credentials must be bound to the exact authorization-server issuer that created them and never reused for a different issuer.

## 5. Connection lifecycle

### Unauthenticated remote server

```text
UI                         app/supervisor                    probe broker
│ POST mcp/start(url)             │                              │
├────────────────────────────────►│ validate target              │
│                                 ├─────────────────────────────►│ connect
│                                 │                              │ negotiate era
│                                 │                              │ tools/list
│                                 │◄─────────────────────────────┤ verified
│                                 │ persist meta + empty auth    │
│                                 │ spawn long-lived broker      │
│◄────────────────────────────────┤ connected + server summary   │
```

A successful connection with zero tools is valid. The UI should show “Connected · 0 tools” with a diagnostic hint, not `auth_failed`.

### OAuth-protected remote server

```text
UI/browser                 app routes                 supervisor/OAuth core       MCP resource / AS
│ POST mcp/start(url)          │                               │                          │
├────────────────────────────►│                               │                          │
│                              ├──────────────────────────────►│ unauthenticated probe    │
│                              │                               ├─────────────────────────►│ 401 + resource metadata
│                              │                               │ discover AS + scopes     │
│                              │                               │ register/select client   │
│                              │                               │ create state + PKCE      │
│◄─────────────────────────────┤ authorize_url                 │                          │
│ open external browser        │                               │                          │
├─────────────────────────────────────────────────────────────────────────────►│ consent
│                              │ callback(code,state,iss)      │                          │
│                              ├──────────────────────────────►│ validate + exchange      │
│                              │                               ├─────────────────────────►│ token
│                              │                               │ encrypt tokens           │
│                              │                               │ spawn + tools/list       │
│◄─────────────────────────────┤ status=connected              │                          │
```

The app route is a browser rendezvous, not the OAuth implementation. It forwards the callback parameters to the supervisor and never receives a token response.

### Reauthorization and step-up

Delete-and-re-add is not a first-class OAuth recovery flow. Add explicit reconnect support:

- An invalid/expired grant that cannot refresh moves the integration to `reauthorization_required`.
- A `403 insufficient_scope` becomes a structured `SCOPE_REQUIRED` error containing the challenged scopes.
- The UI offers “Grant additional access”; it never launches a consent flow from an agent tool call without user action.
- Step-up requests the union of previously requested scopes and newly challenged scopes.
- On success the supervisor atomically replaces the encrypted OAuth state and respawns or refreshes the broker.

## 6. OAuth requirements

The MCP authorization flow is not equivalent to the current Google-specific `server/_oauth.py`. A reusable implementation must include all of the following.

### Discovery

- Start from a real `401 Unauthorized` challenge where possible.
- Parse `WWW-Authenticate`, preferring its `resource_metadata` URL.
- Fall back to the path-specific and root RFC 9728 well-known protected-resource metadata URLs.
- Support both RFC 8414 authorization-server metadata and OpenID Connect discovery.
- Validate metadata relationships and exact issuer values before using endpoints.
- Treat multiple listed authorization servers as independent choices with independent client registrations and tokens.

### Client registration priority

Follow the current MCP preference order:

1. A trusted pre-registered client for that issuer, if a preset provides one.
2. Client ID Metadata Documents (CIMD) when OmniDeck has a viable HTTPS metadata URL and callback strategy.
3. Dynamic Client Registration only as a backwards-compatible fallback.
4. User-entered client information when the server supports none of the above.

DCR is deprecated in MCP `2026-07-28`; it should not be the long-term foundation. For DCR against an OIDC authorization server, send the correct `application_type` for a local/native client.

Self-hosted OmniDeck does not yet have an obvious stable HTTPS CIMD URL plus stable loopback redirect URI. That deployment problem must be resolved explicitly; it must not be hidden behind a hardcoded cloud callback that changes the product's privacy model. A fixed, host-owned loopback callback port is the leading option for desktop, with pre-registration/DCR fallback for other deployments.

### Authorization-code protection

- Generate a high-entropy, single-use `state` value.
- Require PKCE support from authorization-server metadata.
- Use `S256` and retain the verifier only in the pending transaction.
- Record the expected issuer before opening the browser.
- Validate a returned `iss` exactly as required by RFC 9207 before sending the code to a token endpoint.
- Derive redirect URIs from trusted configuration, not the inbound HTTP `Host` header.
- Expire pending transactions and make callback redemption atomic so a code cannot be redeemed twice.

### Token handling

- Send `resource=<canonical MCP resource URI>` on authorization, token, and refresh requests where required.
- Send access tokens only as `Authorization: Bearer` headers and only to the intended MCP resource.
- Request the minimum challenged scopes initially.
- Ask for refresh-token support, but do not assume one will be issued.
- Persist refresh-token rotation atomically. Losing the newest rotated refresh token can permanently disconnect an integration.
- Redact authorization codes, client secrets, access tokens, refresh tokens, cookies, and authorization headers from logs and error strings.

### Token refresh ownership

The long-lived MCP broker should use the SDK's OAuth provider and token storage interface. It needs a narrow way to persist refreshed state without giving general vault-write access to the app:

1. On spawn, the supervisor gives that broker a random, per-process control capability.
2. The broker calls a supervisor `replace_auth` control verb with its integration ID, the capability, and the complete rotated token state.
3. The supervisor validates the capability against the live broker record and atomically rewrites only that integration's encrypted blob.
4. The capability is memory-only and changes on every broker spawn.

This also avoids teaching the app server a general “replace encrypted credentials” operation.

## 7. Broker responsibilities and UDS contract

`integrations/brokers/mcp_broker/` is a normal broker process. It owns one official SDK client and one upstream integration.

### Startup

1. Read and immediately remove endpoint/auth/control values from the environment (or, preferably in a later shared hardening change, receive the secret bundle through an inherited pipe instead of environment variables).
2. Validate the endpoint against the stored network policy.
3. Construct the SDK transport and OAuth provider.
4. Auto-negotiate the current protocol era with legacy fallback.
5. Fetch the complete paginated `tools/list`, validate each definition, and cache the normalized catalog.
6. Print `READY` after protocol and tool discovery succeed. An empty catalog still succeeds.
7. Bind the existing per-integration UDS.

### Semantic verbs

Use OmniDeck's existing framed RPC, not raw MCP messages:

| Verb | Purpose |
|---|---|
| `server_info` | Negotiated version/era, server name/version, capabilities, tool count, catalog revision. |
| `list_tools` | Normalized, paginated tool definitions plus revision/cache metadata. Never includes tokens. |
| `call_tool` | Validate policy and arguments, then call one upstream tool by its original name. |
| `refresh_tools` | Invalidate and refetch the catalog; primarily diagnostic because normal cache invalidation is automatic. |

The official SDK owns MCP request IDs and concurrent calls. There is no JSON-RPC ID rewriting layer in OmniDeck.

### Tool catalog changes

- Honor `ttlMs` and `cacheScope` when the negotiated era provides them.
- Subscribe to tool-list changes through the SDK: `subscriptions/listen` for modern servers and the legacy notification mechanism when negotiated.
- A notification invalidates the broker cache; the next `list_tools` refetches it.
- Each catalog has a stable digest/revision. Runtime Skill resolution compares revisions and rebuilds proxies on the next turn.
- A tool removed during an active turn may return `NOT_FOUND`; do not keep zombie tools indefinitely.

### Calls and results

- Validate arguments against the upstream JSON Schema before sending them.
- Enforce the exact operation grant before calling the SDK.
- Apply per-call timeouts and propagate cancellation.
- Cap inline result bytes independently of the existing 64 MiB RPC frame maximum.
- Prefer `structuredContent` when present, validate it against `outputSchema`, and also preserve useful text content.
- Write bounded image/audio/blob content to the shared downloads directory and return a safe file reference rather than base64 through the model context.
- Do not automatically dereference resource links or external `$ref` URIs.
- Surface `isError: true` content to the model as an actionable tool error.
- Return `INTERACTION_REQUIRED` for unsupported input-required/MRTR results in the first release.

## 8. Dynamic tools inside OmniDeck

Today a tool is a Python callable. Its signature becomes the outbound schema, and `__name__` is its identity. That model cannot faithfully represent an MCP tool with `oneOf`, conditionals, `$defs`, `additionalProperties`, `x-mcp-header`, or other JSON Schema 2020-12 features.

Add a small runtime tool abstraction while preserving ordinary Python functions:

```python
class RuntimeTool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def invoke(self, arguments: dict[str, Any]) -> object: ...
```

`McpRuntimeTool` additionally carries:

- `integration_id`
- the canonical integration operation ID
- `upstream_name`
- `title`
- `output_schema`
- untrusted tool annotations for display
- catalog revision

The SDK tool layer then works over `ToolLike = Callable | RuntimeTool`:

- `callable_to_json_schema()` passes an explicit runtime schema through rather than reconstructing it.
- `_execute_tool_call()` resolves `RuntimeTool.name`, validates its JSON arguments with a bounded JSON Schema validator, and calls `invoke(arguments)`.
- OpenAI, Responses, Anthropic, and Ollama all consume the same normalized explicit schema. A short implementation spike must verify Ollama behavior with full schemas before committing to the adapter shape.
- `AgentState` deduplicates by the normalized tool name helper rather than direct `__name__` access.

### Tool names and collisions

MCP tool names are unique only within one server, while OmniDeck aggregates tools for a model. Generate a deterministic model-facing alias from the immutable integration ID and upstream name:

```text
mcp_<integration-id>__<upstream-tool-name>
```

Normalize to the strictest supported model-provider character set and length, truncating with a stable hash when necessary. Always show the label and original upstream tool name in the tool description and invocation UI. Maintain a direct alias-to-`(integration_id, upstream_name)` map; never recover routing by parsing the alias.

### Full JSON Schema safely

- Accept valid JSON Schema 2020-12 and supported older drafts.
- Require an object at the input root, as MCP does.
- Enforce maximum schema bytes, nesting depth, property count, and validation time.
- Reject external `$ref` resolution; local `$defs` are allowed.
- Reject an individual malformed/unsupported tool with a visible reason while keeping the rest of the server connected.
- If an LLM provider rejects a valid schema feature, disable that tool for that provider with a diagnostic instead of silently weakening its contract.

## 9. Progressive exposure through runtime Skills

Putting every tool from every connected MCP server into the existing `assistant` Skill would scale poorly and damage prompt-cache stability. Represent each running MCP integration as an ephemeral runtime Skill:

```text
skill id:          mcp:github_personal
name:              GitHub (MCP)
description:       34 tools from the connected GitHub server
tools:             current McpRuntimeTool proxies for that integration
```

Extend Skill discovery/resolution so:

- `list_available_skills()` includes connected MCP runtime Skills without writing fake JSON records to the Skill store.
- `load_skill("GitHub (MCP)")` resolves its current broker tool catalog and attaches only that server's tools.
- A persisted loaded runtime Skill re-resolves on the next turn; if the integration is disconnected, resolution skips it with a clear warning.
- Profiles may explicitly include a runtime MCP Skill by stable integration ID.
- The default assistant prompt mentions that connected MCP servers appear as loadable Skills, but it does not automatically load all of them.

This uses OmniDeck's existing progressive-disclosure architecture and keeps “many integrations” practical. If the Skill storage model changes under the Agent Skills RFC, runtime Skills should implement the same resolver interface rather than depend on today's JSON layout.

## 10. Operation grants and the actual trust boundary

The user selects individual discovered operations after the server is connected
and its tool inventory is available. The persisted agent policy is an explicit
allowlist of canonical operation IDs:

| Operation state | Host behavior |
|---|---|
| Not selected | Do not expose to the agent; reject broker-side. |
| Selected and still present | Expose through the agent adapter and allow broker invocation. |
| Newly discovered | Deny until selected. |
| Removed | Stop exposing and reject. |
| Materially changed | Mark for review according to the definition-revision policy. |

There is no MCP capability permission and no read/write access tier. Preserve
`readOnlyHint`, `destructiveHint`, `idempotentHint`, and other annotations only
as visible safety hints. They never select or grant an operation, and all
server-supplied annotations are untrusted unless the server itself is trusted.

### Important limitation

This is an **agent-action gate**, not containment of the remote MCP server:

- A remote server holding a write-capable OAuth grant can act outside an observed `tools/call`.
- A server can lie about `readOnlyHint`.
- A stdio server receiving a broad API token can use it independently of the tool the model selected.

Therefore:

1. Prefer least-privilege OAuth scopes/tokens when the authorization server offers them.
2. Show the actual OAuth scopes during consent and in integration details.
3. Never describe the local toggle as preventing a malicious server from writing.
4. Treat MCP server installation/connection as a trust decision and show its origin prominently.
5. Treat OAuth authorization and the local operation allowlist as separate boundaries; selecting a tool does not prove that the current token can execute it.

## 11. Network and process security

### Remote endpoint and OAuth SSRF

The endpoint and every discovered OAuth URL are attacker-controlled input. Enforce a network policy on every request and redirect, not only when the user first saves the URL:

- Default to public `https://` endpoints.
- Reject credentials embedded in URLs and URL fragments.
- Resolve DNS and reject loopback, link-local, multicast, metadata-service, and private destinations under the public policy.
- Revalidate redirects and final connection addresses to mitigate DNS rebinding.
- Allow private-network servers only behind an explicit user setting and warning; retain an allowlist of approved hosts/IP ranges for that integration.
- Require HTTPS for authorization-server endpoints and reject downgrade redirects.
- Scope bearer tokens to the canonical MCP resource and never forward them across origins.
- Bound response headers, metadata documents, redirects, body bytes, and timeouts.

### Why stdio is deferred

The current supervisor and all brokers run as UID `broker`. The vault is mode `0700` for that same UID. Any `npx`, `uvx`, or arbitrary local MCP child launched by `mcp_broker` would inherit a UID that can open:

```text
/var/lib/omnideck/vault/.master-key
/var/lib/omnideck/vault/creds/*.enc
```

It could consequently decrypt every integration credential. Removing vault paths from its environment does not help.

Stdio can ship only after one of these exists:

- a distinct UID and filesystem view per integration;
- an OCI/subcontainer boundary with no vault mount;
- or an equivalent reviewed sandbox (namespaces, seccomp, no-new-privileges, read-only filesystem, explicit mounts, network policy, resource limits).

Package acquisition also needs integrity/version pinning and a supply-chain policy. A command textbox that executes the latest package from a registry is not an acceptable first release.

## 12. API and UI shape

Names are illustrative; implementation should share HTTP error helpers with the current integration routes.

### HTTP surface

| Endpoint | Purpose |
|---|---|
| `POST /api/integrations/mcp/start` | Validate endpoint, probe, and either connect or return an OAuth authorization action. |
| `GET /api/integrations/mcp/status/{transaction_id}` | Poll discovery/auth/verification state. |
| `GET /api/integrations/oauth/callback` | Generic browser callback; forwards parameters to the supervisor transaction. |
| `POST /api/integrations/{id}/reauthorize` | Begin recovery or scope step-up without deleting the integration. |
| `GET /api/integrations/{id}/mcp/tools` | UI-facing tool catalog, risk hints, rejection reasons, and revision. |

The integration CRUD endpoints continue to list, relabel, change agent operation grants, and remove the installed integration.

### Add wizard

1. Pick a curated preset or “Custom MCP server”.
2. Enter URL and label.
3. Probe and show verified server identity, endpoint, auth requirement, requested scopes, and network posture.
4. For OAuth, open the system browser and poll status.
5. Show the discovered tool inventory and require the user to select the tools the agent may use before activation.

Do not ask for client ID/secret unless discovery shows that pre-registration, CIMD, and DCR are unavailable. Rename the current UI's `oauth_device` concept: it is an authorization-code browser redirect, not an OAuth device flow.

### Integration detail

- Connection/server identity and negotiated protocol era.
- Endpoint and network policy.
- Authentication type, issuer, scopes, token expiry/refresh status (never token values).
- Tool inventory with annotation-derived risk labels and locally effective policy.
- Reauthorize, refresh tools, and disconnect actions.
- Honest warning that tool descriptions/results and server annotations come from the connected server.

## 13. States and errors

Installed MCP integrations need more precise states than `running | auth_failed | broken`:

| State | Meaning | Recovery |
|---|---|---|
| `running` | Broker and upstream tool catalog available. | None. |
| `reconnecting` | Transient network/protocol recovery. | Automatic bounded retry. |
| `reauthorization_required` | Refresh unavailable/rejected or grant revoked. | User starts browser reauthorization. |
| `additional_scope_required` | A call produced an insufficient-scope challenge. | User reviews and grants step-up scopes. |
| `misconfigured` | Invalid endpoint, metadata, schema, or unsupported auth registration. | Edit/reconnect; show precise diagnostic. |
| `broken` | Repeated internal or upstream failure. | Retry/reconnect, then logs. |

Broker errors should map into typed `broker_client` exceptions (`IntegrationReauthorizationRequired`, `IntegrationScopeRequired`, `IntegrationProtocolError`, etc.) rather than forcing string matching.

## 14. Observability and privacy

Log enough to debug interoperability without logging secrets or user data:

- integration ID, endpoint origin (path only when safe), negotiated protocol version/era;
- server identity and capability names;
- tool catalog revision/count and rejected-tool reasons;
- upstream tool name, duration, success/error class, and bounded byte counts;
- OAuth transaction phase and issuer, never codes/tokens/verifiers;
- token refresh success/failure without token contents.

Do not log tool arguments or results by default. They commonly contain PII, document content, queries, and credentials. The UI's existing summarized tool-call event should show the model-facing alias and integration label.

## 15. Verification strategy

### Protocol fixtures

Use real subprocess/HTTP fixtures and the official SDK, covering both protocol eras:

- modern `2026-07-28` unauthenticated Streamable HTTP;
- modern OAuth-protected server with RFC 9728 + RFC 8414/OIDC discovery;
- a handshake-era server to prove SDK fallback;
- empty tool list;
- paginated tools and TTL/cache scope;
- tool-list change invalidation;
- full JSON Schema 2020-12, local `$defs`, invalid external `$ref`, malformed `x-mcp-header`;
- text, structured, image/audio, resource-link, `isError`, and oversize results;
- cancellation, timeout, reconnect, and concurrent calls.

### OAuth tests

- challenge and both protected-resource well-known fallbacks;
- multiple authorization servers and issuer-bound registrations;
- pre-registration, CIMD, DCR fallback, and manual client input;
- PKCE required and S256 used;
- state mismatch, replay, expiry, and concurrent callbacks;
- `iss` match/mismatch behavior;
- mandatory resource indicator on authorization/token/refresh;
- refresh-token rotation persisted before old token is lost;
- 401 refresh retry capped at one, then reauthorization state;
- insufficient-scope union and user-driven step-up;
- log/error redaction.

### Security tests

- public policy rejects loopback/private/link-local/metadata targets;
- every redirect and post-DNS address is revalidated;
- HTTPS downgrade and cross-origin bearer forwarding are rejected;
- schema/result/catalog size and depth caps;
- unselected, new, removed, and revision-invalidated operations are rejected in the broker before the SDK call;
- app process cannot call `replace_auth` without the live broker capability;
- no local stdio command surface exists in the first release.

### Product/e2e tests

- custom URL, unauthenticated success;
- OAuth popup/browser success, cancel, denial, expiry, and retry;
- connected zero-tools state;
- runtime MCP Skill appears, loads, persists across turns, refreshes next turn, and disappears cleanly on disconnect;
- tool origins and risky-tool labels are visible;
- reauthorize without delete/re-add.

## 16. Proposed implementation slices

Slices are dependency ordered. MCP should remain behind a feature flag until Slice 4 so OAuth is present in the first user-visible release.

### Slice 0 — compatibility spike

- Pin and exercise the official Python SDK 2.x against one modern and one legacy fixture.
- Verify full-schema tool conversion for OpenAI, Responses, Anthropic, and Ollama.
- Prove OAuth callback integration and a persistent `TokenStorage` adapter.
- Resolve the desktop/self-hosted redirect URI and CIMD strategy.

Exit criterion: recorded decisions for SDK version range, callback origin/port, provider schema limits, and any SDK gaps.

### Prerequisite — integration core refactor

- Complete the accepted work in `plans/integration_core_refactor.md`.
- Remove capability/read-write authorization from the new integration model.
- Separate canonical integration operations from agent tools and model-provider connections.

### Slice 1 — explicit-schema operation and agent-tool adapters

- Add explicit-schema integration-operation and `RuntimeTool` / `ToolLike` adapters.
- Normalize schema generation, execution, naming, and `AgentState` deduplication.
- Add bounded JSON Schema validation.
- No MCP network behavior yet.

### Slice 2 — generic remote MCP broker

- Add v3 integration config, an MCP integration catalog entry, and the reusable MCP broker driver.
- Support unauthenticated public-HTTPS Streamable HTTP.
- Implement semantic UDS verbs, tool cache/revision, results, and exact operation-grant enforcement.
- Add network-policy enforcement.

### Slice 3 — progressive runtime Skills

- Project each connected MCP integration as a runtime Skill.
- Resolve current tool proxies on load and next-turn restore.
- Add skill/catalog UI origin labels and integration detail tool inventory.

### Slice 4 — provider-neutral OAuth and connection UX

- Move transaction ownership into the integration boundary.
- Implement discovery, registration choices, PKCE, issuer validation, resource indicators, token persistence/refresh, reauthorization, and scope step-up.
- Add the MCP Add wizard and typed states/errors.
- Ship the feature after security/e2e coverage passes.

### Slice 5 — hardening and richer interop

- Complete binary/resource result side channels and advanced schema diagnostics.
- Add optional human-confirmation policy as a layer distinct from the operation allowlist.
- Add curated presets and migration of Google Workspace to the shared OAuth core where doing so reduces rather than increases risk.

### Later — sandboxed stdio

- Choose and threat-model the sandbox.
- Pin/package trusted server artifacts.
- Add process, filesystem, network, CPU, memory, and output limits.
- Only then add the stdio transport to the generic broker config.

## 17. Open decisions

1. **CIMD and redirect URI:** Can the desktop host own a stable loopback callback port across platforms, and what is the fallback for container-only deployments?
2. **Private-network MCP:** Is explicit per-integration LAN access enough, or should it be a global advanced setting plus an integration allowlist?
3. **Confirmation UX:** Should `destructiveHint`/unknown tools prompt at every call, once per conversation, or through persistent per-tool policy?
4. **Rich results:** Which content types should be first-class UI events in the first release versus safe file/text fallbacks?
5. **Catalog presets:** Should a preset keep its provider slug while declaring `broker_kind: mcp`, or should every instance use `slug: mcp` plus a separate preset identifier?
6. **SDK pin:** Use a conservative compatible range after the spike or an exact version with intentional upgrade PRs?
7. **Google OAuth migration:** Share the new OAuth core immediately or let both paths coexist until MCP proves the abstraction?

## 18. Protocol references

- [MCP 2026-07-28 authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Authorization server discovery](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/authorization-server-discovery)
- [Client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)
- [Authorization security considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)
- [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [Official Python SDK OAuth client guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/oauth-clients.md)
