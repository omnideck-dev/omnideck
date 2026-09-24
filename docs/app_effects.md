# Application Effects

Application Effects are typed, one-time messages for coordination between
feature owners. They are delivered synchronously in memory and are never
retained as application state.

## Envelope

Every effect uses the same envelope:

```js
{
    type: 'workspace/root-resource-available',
    payload: {
        conversationId,
        agentId,
        agentName,
        resourceId,
    },
    meta: {
        source: 'conversation',
        correlationId,
    },
}
```

- `type` is a stable, domain-prefixed name from `APP_EFFECT_TYPES`.
- `payload` contains all domain data. It is `null` when there is no data.
- `meta` is optional transport context. Domain data does not belong there.
- Payload fields use camel case.

The payload registry in `appEffects.types.ts` is the source of truth for the
TypeScript contract. The provider also rejects messages that omit `payload`,
so legacy flat messages do not silently reintroduce a second format.

## Naming

- `*-requested` is an intent asking one feature owner to perform an operation.
- Past-tense or state-oriented names are facts that any number of features may
  observe, such as `workspace/root-resource-available`.
- Lifecycle notifications describe timing and do not imply cancellation or a
  response, such as `desktop/views-closing`.

Components should normally call a narrow domain command such as
`openAgentWorkspaceResource(...)`. The owning adapter may use an Application
Effect internally, without exposing raw event names to callers.

## Delivery Semantics

Application Effects are:

- synchronous;
- delivered only to subscribers mounted at dispatch time;
- safe for multiple subscribers;
- isolated so one throwing subscriber does not stop the others;
- not persisted, replayed, retried, acknowledged, or returned to the sender.

Use an effect for transient facts, invalidations, and cross-feature requests.
Durable facts—open Views, conversations, catalogs, Workspace data, and similar
state—remain in their owning feature store.

If effects later cross processes or require guaranteed delivery, introduce a
separate transport with explicit IDs, timestamps, versions, retries, and
acknowledgements instead of changing these in-memory semantics implicitly.
