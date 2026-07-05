# App Router

> Detailed design for the built-in Omnideck route that lets an app frontend
> invoke public app callables without exposing arbitrary backend routes, core
> callables, local callables, storage, files, or integrations directly.

## Relationship To Other Designs

[callable-runtime.md](callable-runtime.md) defines callable packaging,
resolution, execution, isolation, dependency checks, and logs.
[core-callables.md](core-callables.md) indexes the first core callable surface
and links to the detailed storage, files/artifacts, HTTP/API, and integration
wrapper designs.
[feature-flags.md](feature-flags.md) defines release gates and disabled
behavior for app runtime routes.

This document defines only the app invoke API and router behavior. It does not
define iframe hosting, SDK injection, design tokens, app manager UI, or the full
frontend isolation model. Those should stay in a separate frontend/isolation
design.

## Core Rule

The app frontend invokes public app callables only:

```text
POST /api/apps/{app_id}/invoke/{route}
```

It cannot invoke:

- core callables,
- local callables,
- vendored local callables,
- private app callables,
- app storage APIs,
- file APIs,
- integration APIs,
- arbitrary app-defined HTTP handlers.

If the app needs storage, files, HTTP, Drive, or orchestration, that logic lives
inside an app callable. The app callable declares dependencies and invokes core,
private app, or vendored callables through the parent-managed callable runtime.

The app router is also feature-flag gated. If `ai_workbench.enabled` or
`ai_workbench.runtime_enabled` is off, frame creation, frame serving, invoke,
call polling, and cancellation routes return `FEATURE_DISABLED` before loading
app manifests or starting runner work. The callable runtime repeats the runtime
flag check before app runner launch so route bugs do not become execution bugs.

## Goals

- Give app frontends one stable backend invocation surface.
- Keep router authorization simple: public app callable or nothing.
- Keep app context injection server-owned.
- Validate request input and callable output with schemas.
- Return structured results and errors that a frontend can render and the agent
  can debug.
- Return `call_id` for every accepted invocation.
- Make failures easy to inspect through callable run logs.

## Non-Goals

- App-defined REST routes.
- Direct frontend access to core callables.
- Direct frontend access to integrations or credentials.
- Direct frontend access to arbitrary Omnideck `/api/*` routes.
- A replacement for broker permission enforcement.
- Full iframe/bridge design.
- User file uploads into apps for v1.
- App-created downloadable artifacts for v1.

## Route Shape

Primary invoke route:

```text
POST /api/apps/{app_id}/invoke/{route}
```

Optional route for cancellation:

```text
POST /api/apps/{app_id}/calls/{call_id}/cancel
```

Optional route for polling if the initial implementation supports async jobs:

```text
GET /api/apps/{app_id}/calls/{call_id}
```

For v1, prefer synchronous HTTP invocation with timeouts. Add polling only when
an app action naturally exceeds the request timeout budget.

## App And Version Resolution

The router resolves the app before reading request args:

1. Confirm `app_id` exists.
2. Validate the server-minted frame token.
3. Confirm the token is bound to the same `app_id`, active version or draft id,
   frame id, user/session, and route namespace.
4. Resolve the active app version for this install/user.
5. Load the app version manifest from app-owned storage.
6. Load the callable registry view for that app version.
7. Resolve `route` to an app-scoped callable in that version.
8. Reject if the callable is missing or private.

The route does not accept `app_version` from the frontend in v1. The active
version is server-side state. Rollback or version selection belongs to app
management APIs, not arbitrary invoke requests.

The route also does not trust app-frame code to name its own app. The parent
bridge attaches an app-scoped frame token, and the server rejects a request when
the token binding and the URL `app_id` disagree. This prevents one app frame from
invoking another installed app's public callables even if the frame can induce a
malformed bridge request.

If a future UI needs previewing a draft or non-active version, use a separate
editor/preview route with explicit agent/user tooling semantics. Do not overload
the normal saved-app invoke route.

## Callable Name Resolution

`route` is the public app callable route, not a fully qualified runtime
ref. For example:

```text
POST /api/apps/app_project_backlog/invoke/list_backlog
```

The app manifest maps that name to an app callable package:

```json
{
  "callables": {
    "list_backlog": {
      "id": "app.list_backlog",
      "version": "1",
      "app_visibility": "public",
      "path": "callables/list_backlog/"
    },
    "fetch_github_issues": {
      "id": "app.fetch_github_issues",
      "version": "1",
      "app_visibility": "private",
      "path": "callables/fetch_github_issues/"
    }
  }
}
```

The route may accept only simple names:

```text
[A-Za-z0-9_][A-Za-z0-9_-]{0,127}
```

Reject names containing slashes, dots, `@`, URL-encoded traversal, or namespace
prefixes. This prevents the route from becoming a generic callable runner.

## Request Envelope

Use an envelope instead of passing raw callable args as the top-level request.
That leaves room for router metadata without colliding with callable input
schemas.

```json
{
  "args": {
    "status": "todo",
    "limit": 50
  },
  "client_request_id": "optional-stable-id"
}
```

Fields:

| Field | Required | Meaning |
|---|---:|---|
| `args` | yes | JSON object validated against the public app callable input schema |
| `client_request_id` | no | Client-generated id for UI correlation and optional idempotency |

`args` must be an object. If a callable takes no inputs, `args` is `{}`.

The router should reject unknown top-level fields in v1. Callable-specific data
belongs under `args`.

## Invocation Context

The router calls the runtime with server-owned context:

```text
caller: app_router
app_id: resolved app id
app_version: active version
frame_id: validated app frame id
frame_token_id: server-side token id, not exposed to the runner
route: public app action route
request_id: server request id
client_request_id: optional
```

The app frontend never supplies:

- `app_id` for storage scoping,
- `app_version`,
- caller scope,
- user identity,
- integration credentials,
- storage roots,
- file roots.

When the public app callable runs, nested callable calls inherit the app context
and produce a call tree under the same top-level `call_id`.

## Validation

The router validates in this order:

1. HTTP method and content type.
2. app id and active version.
3. callable name syntax.
4. callable existence and `app_visibility: public`.
5. request envelope shape.
6. `args` against the callable input schema.
7. output against the callable output schema after execution.

Validation failure before invocation returns no callable `call_id` unless a run
record was already created. Validation failure after the runtime creates a run
record returns that `call_id` so the agent can inspect the failure.

## Response Envelope

Successful app callable result:

```json
{
  "ok": true,
  "call_id": "call_abc123",
  "result": {
    "items": [],
    "next_cursor": null
  },
  "effects": [
    {
      "kind": "app.storage.read",
      "summary": "Read backlog items"
    }
  ]
}
```

Fields:

| Field | Meaning |
|---|---|
| `ok` | true for successful callable completion |
| `call_id` | top-level callable run id |
| `result` | callable result after output-schema validation |
| `effects` | sanitized effect summaries safe for frontend display |

The router should not include stdout, stderr, raw logs, host paths, environment
details, credentials, auth headers, or raw broker payloads in the response.

## Error Envelope

Every router error should use one shape:

```json
{
  "ok": false,
  "call_id": "call_abc123",
  "error": {
    "code": "INTEGRATION_PERMISSION_DENIED",
    "message": "Drive writes are disabled for app integration 'drive_backup'.",
    "retryable": false,
    "details": {
      "integration_alias": "drive_backup",
      "resolved_integration_id": "google_workspace"
    }
  }
}
```

`call_id` is `null` or omitted when invocation never started:

```json
{
  "ok": false,
  "error": {
    "code": "APP_CALLABLE_NOT_FOUND",
    "message": "This app does not expose an action named 'close_all_issues'.",
    "retryable": false
  }
}
```

Router-level error codes:

| Code | HTTP | Meaning |
|---|---:|---|
| `APP_NOT_FOUND` | 404 | App id does not exist |
| `APP_VERSION_NOT_FOUND` | 409 | Active version pointer is invalid or missing |
| `APP_CALLABLE_NOT_FOUND` | 404 | No callable with that public route name |
| `APP_CALLABLE_PRIVATE` | 403 | Callable exists but is not public |
| `BAD_REQUEST` | 400 | Malformed envelope, invalid name, or unsupported content |
| `VALIDATION_ERROR` | 422 | Args or result failed schema validation |
| `CALLABLE_TIMEOUT` | 504 | Top-level callable exceeded timeout |
| `CALLABLE_CANCELLED` | 499 | Invocation was cancelled by user/client |
| `CALLABLE_RUNTIME_ERROR` | 500 | Runner crashed or returned an invalid runtime frame |
| `CORE_CALLABLE_DISABLED` | 409 | A retained core dependency is disabled |
| `FEATURE_DISABLED` | 403 | AI workbench apps or this app runtime surface are disabled by feature flag |

Core callable errors such as `INTEGRATION_NOT_CONNECTED`,
`INTEGRATION_PERMISSION_DENIED`, `STORAGE_REVISION_CONFLICT`, `FILE_TOO_LARGE`,
and `UPSTREAM_TIMEOUT` pass through the same envelope.

The app frontend should render `message` and keep `call_id` available for a
"debug with agent" action. Detailed logs stay behind callable-run inspection
tools/APIs.

## HTTP Status Policy

Use HTTP status for router/request transport status, not upstream integration
status.

Examples:

- A GitHub API response of `404` returned by the `integration.github.request@1`
  facade can still be an app callable success if the callable handled it and
  returned a result.
- A callable-thrown structured error maps to the closest router HTTP status, but
  the frontend should key off `error.code`.
- Input validation errors use `422`.
- Missing/private app callables use `404`/`403`.
- Runtime crashes use `500`.
- Timeouts use `504`.

Do not tunnel all errors through `200`. The envelope is stable, but HTTP status
should remain useful for browser tooling, proxies, and tests.

## Effects In Responses

The router can include sanitized effect summaries for UI feedback:

```json
{
  "kind": "drive.write",
  "summary": "Uploaded project-backlog-backup.json to Drive"
}
```

Effects are derived from callable run events and manifest metadata. They are
not permission grants and should not include credentials, auth headers, request
bodies, full response bodies, or raw file paths.

The detailed authoritative record remains the callable run log.

## Cancellation And Timeouts

Each invoke request gets a top-level timeout. Suggested defaults:

```text
interactive reads: 30 seconds
ordinary writes/exports: 60 seconds
long-running backups/imports: explicit async job path
```

If the HTTP request disconnects, the router should decide per action whether to
cancel immediately or let the callable complete. For v1, default to cancelling
when the client disconnects unless the callable was explicitly started as a
background/async action.

Cancellation behavior:

1. Mark the top-level `call_id` as cancelling.
2. Ask the callable runtime to cancel the call tree.
3. Kill runner subprocesses that do not exit within the grace period.
4. Record `CALLABLE_CANCELLED` in logs.
5. Return or expose the final cancellation status.

Nested core integration calls should use their own broker timeouts. A cancelled
app invocation should not leave orphaned runner processes.

## Idempotency

The router accepts optional `client_request_id` for UI correlation. It is not a
global idempotency guarantee by default.

For mutating public callables that need retry safety, the app callable should
implement idempotency using app storage and expose a stable app-level operation
id in its own schema. The router may later add generic idempotency for
`client_request_id`, but that requires storing completed response envelopes and
knowing which calls are safe to replay.

## XSRF And Frontend Boundary

The invoke route is mutating from Omnideck's perspective even when the callable
only reads app storage. It can trigger arbitrary app code and integration-backed
effects. It must require the same XSRF protection as other mutating routes,
including whatever fix closes the current `PATCH` gap.

For same-origin development routes, require the existing non-simple request
header guard, for example:

```text
X-Requested-With: XMLHttpRequest
```

For production app hosting, the v1 model is an opaque-origin sandboxed frame
with a parent bridge. The untrusted app frame should not be able to call
`/api/apps/.../invoke` directly unless the bridge deliberately forwards the
request. The bridge attaches the necessary XSRF/session context and a
server-minted app-scoped frame token.

This router design only requires that invoke requests come through a trusted
Omnideck-controlled path and carry a valid token bound to the target app. A
future dedicated app origin must preserve that property.

## Logs And Debug Handoff

The router creates or receives a top-level `call_id` for each invocation that
enters the callable runtime. The run log should include:

- app id and app version,
- public callable route name,
- resolved callable id/version/hash,
- client request id when present,
- input validation outcome,
- nested callable call tree,
- sanitized effect summaries,
- result validation outcome,
- duration, timeout, cancellation, and runner failure details.

Frontend errors should expose `call_id`. The user can ask the agent to debug an
app action, and the agent can inspect that run through callable-run tools such
as:

```text
get_callable_run(call_id)
export_callable_support_bundle(call_id)
```

Support bundles require explicit user action and redaction. Run logs and support
bundle inputs are described in
[callable-runtime.md](callable-runtime.md#logs-results-and-retention).

## Backlog Manager Examples

List backlog:

```text
POST /api/apps/app_project_backlog/invoke/list_backlog
```

```json
{
  "args": {
    "status": "todo",
    "limit": 100
  }
}
```

The public app callable may call:

```text
omnideck.app.storage.list@1
integration.github.request@1
```

Backup project:

```text
POST /api/apps/app_project_backlog/invoke/backup_project
```

```json
{
  "args": {
    "upload_to_drive": true
  },
  "client_request_id": "backup-2026-07-05T20:30:00Z"
}
```

The public app callable may call:

```text
omnideck.app.storage.export@1
integration.google_drive.upload_file@1
omnideck.app.storage.update@1
```

The frontend receives a structured result and a `call_id`, not the backup file's
host path or Drive credentials.

## Implementation Notes

Suggested server-side flow:

```text
handle_invoke(request)
  enforce ai_workbench.enabled and ai_workbench.runtime_enabled
  parse path app_id/route
  enforce XSRF/session guard
  resolve active app version
  resolve public app callable
  parse and validate envelope
  validate args
  call invoke_callable(app callable ref, args, context)
  validate result
  normalize effects
  return response envelope
```

The app router should be thin. It should not learn storage, Drive, GitHub, or
backup-specific behavior. Those belong in app callables and core callables.

## Open Decisions

- Whether v1 needs the async `GET /calls/{call_id}` route or only synchronous
  invoke plus cancellation.
- Whether router-level idempotency is worth adding before real app workflows
  prove retry needs.
- Exact timeout defaults by callable manifest effect class.
- How much sanitized effect detail the frontend should receive by default.
- Whether a later version should add user-selected input refs for file/artifact
  uploads into app actions.
- Whether a later version should let app callables return artifact/download
  handles through the router.
