# Integration core refactor — accepted architecture

**Status:** Accepted design direction. This refactor is a prerequisite for MCP
integration work.

**Scope:** The integration catalog, broker lifecycle, native integration
operations, agent exposure, persisted grants, and the boundary needed by a
future Custom App SDK. This document does not implement MCP or the Custom App
SDK.

## 1. Locked decisions

1. **Authorization is an explicit allowlist of canonical integration
   operations.** The new model has no `Capability`, `Access`, read-only tier, or
   read/write tier. An operation is callable for a consumer or it is not.
2. **An integration operation is not an LLM tool.** Operations are stable,
   structured application APIs. Agent tools are one presentation over those
   APIs; a future Custom App SDK is another.
3. **Catalog entries and broker drivers are distinct.** A catalog entry is an
   installable provider or preset. A driver is the privileged runtime
   implementation. Many catalog entries may use one driver.
4. **LLM providers are not tool integrations.** Brokered LLM providers continue
   to reuse the vault, supervisor, process isolation, health monitoring, and
   Unix-socket infrastructure, but they have their own domain type and catalog.
   Sharing infrastructure does not make them `IntegrationOperation` providers.
5. **Existing installations migrate in place.** IDs, encrypted credentials,
   OAuth tokens, labels, and timestamps survive. Legacy capability permissions
   are expanded once into explicit native-operation grants.
6. **New or newly discovered operations are denied by default.** Bulk UI
   actions may select multiple operations, but persistence always records the
   resulting explicit selection.

## 2. Vocabulary

| Concept | Meaning |
|---|---|
| `BrokerDriver` | Privileged executable plus its spawn, secret-binding, host-path, health, and socket contract. |
| `BrokeredConnection` | Common persisted/lifecycle base for anything using a broker process. |
| `IntegrationCatalogEntry` | User-selectable integration provider or preset, such as iCloud, Google Workspace, Custom HTTP, or GitHub MCP. |
| `IntegrationInstance` | One configured external service/account, such as “Google Workspace · Work.” |
| `IntegrationOperation` | Stable structured action on one integration instance, such as `email.messages.search` or `calendar.events.create`. |
| `OperationGrant` | An explicit allow/deny decision for one operation and one consumer. Absence means deny. |
| `InvocationContext` | Identifies the consumer invoking an operation. Initially the only consumer is `agent`; later it can identify a Custom App. |
| `AgentTool` | LLM-facing name, description, schema, routing wrapper, and result formatting projected from integration operations. |
| `ModelProviderCatalogEntry` | Definition of an LLM provider connection, such as OpenAI, Anthropic, or OpenRouter. |
| `ModelProviderInstance` | A configured model-provider connection consumed by `sdk.providers`, not by the integration-operation API. |

User-facing copy may call integration operations “tools.” Code and persisted
policy use operation IDs so model-facing tool aliases can change independently.

## 3. Layering

```text
                                  broker platform
                         ┌────────────────────────────┐
                         │ vault / lifecycle / UDS    │
                         │ process isolation / health │
                         └──────────────┬─────────────┘
                                        │
                         ┌──────────────┴──────────────┐
                         │                             │
                integration domain            model-provider domain
              IntegrationInstance             ModelProviderInstance
              IntegrationOperation            provider SDK protocol
                         │                             │
             ┌───────────┴───────────┐                 │
             │                       │                 │
       AgentTool adapter      future Custom App SDK    LLM runtime
```

The common broker platform owns only generic concerns:

- encrypted secret storage;
- non-secret connection metadata;
- process spawn, readiness, restart, and teardown;
- socket ownership and resolution;
- bounded control channels such as rotated-token persistence;
- common health/error state.

It does not define operation grants, LLM tool schemas, model-provider APIs, or
provider-specific OAuth semantics.

## 4. Catalog entries and drivers

The current `CatalogEntry` combines a user-selectable provider with executable
details. Replace it with two explicit layers.

Illustrative shapes:

```text
BrokerDriver
  id
  command
  secret_bindings
  host_path_bindings
  socket_protocol

IntegrationCatalogEntry
  id
  presentation
  auth_definition
  driver_id
  driver_config
  operation_source

ModelProviderCatalogEntry
  id
  presentation
  provider_protocol
  driver_id
  driver_config
```

Examples:

```text
iCloud ───────────────► email driver
Gmail app password ───► email driver
Google Workspace ─────► google-workspace driver
Custom HTTP ──────────► HTTP driver

GitHub MCP preset ────┐
Glean MCP preset ─────┼► MCP driver
Custom MCP ───────────┘

OpenAI ───────────────┐
Anthropic ────────────┼► LLM HTTP proxy driver
OpenRouter ───────────┘
```

The backend catalog is authoritative for IDs, auth requirements, driver
selection, provider configuration, and static operation definitions. The UI
receives a safe serialized projection; broker commands and secret bindings are
never sent to it.

## 5. Integration operations

An operation is protocol-neutral and returns structured data:

```text
IntegrationOperation
  id
  title
  description
  group                         optional presentation metadata
  input_schema
  output_schema
  source                        native_catalog | discovered
  definition_revision          for change detection
  safety_hints                 optional, descriptive, non-authoritative
```

There is deliberately no required read/write or capability field. Safety hints
such as destructive behavior, external communication, idempotence, or MCP
annotations may be displayed, but they do not grant access.

Operation IDs are stable application contracts:

```text
canonical operation    email.messages.send
broker implementation  send_message
agent tool              send_email
Custom App SDK          integrations.invoke(instance_id, "email.messages.send", args)
```

Native operations come from trusted static definitions. MCP operations are
discovered per instance. Both use the same descriptor and invocation surface.

## 6. Invocation and grants

The supported application entry point is an integration service, not the raw
broker client:

```text
IntegrationService.list_instances(context)
IntegrationService.list_operations(context, instance_id)
IntegrationService.invoke(context, instance_id, operation_id, arguments)
```

Invocation succeeds only when the operation is:

```text
defined or currently discovered
  INTERSECT available under the current remote authorization
  INTERSECT explicitly granted to the invocation consumer
```

For the initial product, only `InvocationContext(consumer="agent")` exists.
The persisted agent grant is an explicit operation-ID allowlist; absence is
deny. The broker rechecks the exact operation ID before contacting the remote
service.

The UI may provide “Select all,” “Select none,” search, grouping, and trusted
catalog recommendations. These controls only edit individual operation
selections. There is no persisted group or access-tier permission.

The generic HTTP integration exposes one write-capable-in-practice operation,
for example `http.request`. Selecting it permits the complete generic request
surface. OmniDeck does not claim to provide a read-only generic HTTP mode.

## 7. Agent tools and the future Custom App SDK

Current integration tool functions mix transport calls, error conversion,
model descriptions, argument shaping, and result prose. Refactor them into:

```text
integration operation implementation
  structured arguments
  structured result
  structured errors

agent adapter
  model-facing name and description
  model schema adaptation
  integration-instance selection
  bounded/model-friendly result formatting
```

An agent adapter may aggregate the same operation across several integration
instances. That does not change the canonical operation identity or grants on
each instance.

Later, the Custom App host bridge can add:

```text
omnideck.integrations.list()
omnideck.integrations.listOperations(instanceId)
omnideck.integrations.invoke(instanceId, operationId, arguments)
```

Custom Apps must call through the trusted host. They never receive vault
credentials, broker socket paths, or access to the raw broker protocol. When
Custom App access is implemented, each app gets its own operation grants and
cannot inherit the agent grant implicitly.

The core invocation interface accepts an `InvocationContext` now so app
identity can be added without changing every operation contract. App discovery,
identity, consent UI, and app-specific grant persistence are deferred.

## 8. LLM providers on the broker platform

The existing `llm_*` records use integration storage and lifecycle only because
those are currently the names of the shared primitives. They do not expose
integration operations and must not receive empty/fake operation grants.

Introduce a discriminator in the common connection metadata:

```text
kind: integration | model_provider
```

Then use domain-specific records:

```text
IntegrationInstance
  common brokered-connection fields
  integration_catalog_entry_id
  agent_operation_grants
  non-secret integration config

ModelProviderInstance
  common brokered-connection fields
  model_provider_catalog_entry_id
  provider protocol/config
```

The LLM proxy remains a transparent authenticated HTTP proxy over UDS. The
provider SDK continues to speak OpenAI/Anthropic protocols through it. It is
not converted into `IntegrationOperation` calls, and model API endpoints are
not selectable agent tools.

The application keeps separate APIs and UI:

- `/api/integrations` lists only `kind=integration` records;
- `/api/providers` lists model providers;
- the common supervisor may expose internal connection-management verbs used
  by both domain routes.

This removes slug-prefix checks such as `slug.startswith("llm_")` from domain
logic while retaining the security and lifecycle benefits of the broker.

### Existing LLM-provider migration

On metadata migration, existing records whose known catalog entry is an
`llm_*` provider become `kind=model_provider`. Preserve their IDs and socket
names initially so `sdk.providers` keeps working during the transition. They
receive no integration-operation policy. Their encrypted API keys are not
rewritten.

Direct/no-secret providers such as a local Ollama endpoint may remain in the
existing direct-provider settings path; unifying direct and brokered provider
configuration is a separate decision.

## 9. Backward-compatible metadata migration

Existing integration records migrate deterministically:

```text
legacy capability off  -> grant no operations from that legacy group
legacy capability r    -> grant the exact native operations historically exposed at r
legacy capability rw   -> grant the exact native operations historically exposed at rw
```

This is a version-specific migration table, not a property retained on the new
operation model. New operations are absent from the generated allowlist and
therefore denied.

Existing `http:r` cannot be preserved without either retaining argument-level
method policy or widening access. It migrates with `http.request` denied and a
visible review notice. Existing `http:rw` grants `http.request`.

During a compatibility window:

- API reads return the new operation grants and a deprecated legacy permission
  projection;
- API writes accept either old capability permissions or new operation grants,
  but reject requests containing both;
- a legacy projection is emitted only when an operation selection is exactly
  representable as `off`, `r`, or `rw`; custom subsets project conservatively
  to `off` so rollback cannot broaden authority;
- metadata writes remain atomic and a one-time pre-migration metadata backup is
  retained;
- migration is idempotent and leaves unknown/missing catalog entries untouched
  for recovery.

## 10. Implementation sequence

1. **Common broker vocabulary**
   - Introduce broker drivers and the `integration | model_provider`
     discriminator.
   - Split integration and model-provider catalog types while keeping existing
     IDs/socket names compatible.
   - Make the backend catalog the semantic source of truth for the UI.
2. **Canonical native operations**
   - Define operation descriptors, structured results/errors, and the
     `IntegrationService` invocation interface.
   - Wrap existing broker verbs without rewriting provider clients.
3. **Agent projection**
   - Reduce `tools/integrations/*` to agent-specific adapters.
   - Preserve current agent tool names and output behavior with parity tests.
4. **Explicit operation grants**
   - Add exact broker enforcement, metadata migration, compatibility API, and
     per-operation UI selection.
   - Remove `Capability`, `Access`, and `Permissions` after the compatibility
     path no longer imports them at runtime.
5. **Dynamic operation providers**
   - Add list/revision/invocation support for per-instance dynamic operations.
   - Begin MCP implementation on this foundation.

## 11. Required invariants

- Operation IDs, not LLM aliases or broker verbs, are persisted in grants.
- Missing grants deny.
- New native or discovered operations deny by default.
- The broker rejects an ungranted operation even if a caller bypasses agent
  tool exposure.
- Operation implementations return structured data; LLM prose lives only in
  agent adapters.
- Custom Apps never access credentials or broker sockets directly.
- Model-provider connections never appear as selectable integration
  operations.
- Migration and downgrade projections never increase authority.
