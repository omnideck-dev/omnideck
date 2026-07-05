# Integration Wrapper Core Callables

> Design for turning current integration tools into core callables while keeping
> broker permissions authoritative. Includes Drive upload as the first concrete
> integration wrapper needed by the project backlog app.

## Scope

Core integration callables are stable programmatic wrappers around existing
broker verbs. They let app/local callables use connected integrations without
direct credential access and without introducing a second permission model.
For app-building agents, connected integrations appear in the callable catalog
as integration facade callables. App callables depend on those facades. Omnideck
derives app-level integration aliases from those dependencies and resolves each
alias to a connected account server-side using the app install mapping.

The first concrete wrapper in this category is:

```text
omnideck.drive.upload_file@1
```

Other email, calendar, contacts, Drive, and API wrappers should follow the same
pattern as their existing agent-facing tools are migrated.

## Wrapper Pattern

Each integration tool should split into three layers:

```text
Agent-facing tool binding
  - current LLM name/docstring/argument UX
  - may format JSON result as text for the agent
  - may keep path-based convenience args where useful

Core callable
  - stable programmatic schema
  - structured JSON result
  - file_ref-based file inputs/outputs
  - effect metadata and invocation logs
  - maps broker errors to callable errors

Broker verb
  - credentials
  - upstream client
  - Capability x Access enforcement
  - service-specific safety checks
```

The LLM-facing surface does not have to change when the core callable is added.
For example, today's `call_api(...)` tool can continue returning formatted text
to the agent, while app/local callables invoke `omnideck.http.request@1` and get
structured JSON.

Current tools can migrate incrementally:

1. Add a core callable manifest with a Python import target.
2. Move the existing broker-call logic into a structured core implementation or
   wrap the existing function with a structured adapter.
3. Update the agent binding to invoke the core callable or keep sharing the same
   lower-level helper.
4. Preserve the old tool name, docstring shape, and result formatting.
5. Add effect metadata to the core manifest.

## What Stays In Broker Permissions

The broker and supervisor remain the source of truth for:

- whether an integration exists and is connected,
- encrypted credential storage and refresh,
- OAuth scopes and API tokens,
- capability/access grants such as `drive:rw` or `http:r`,
- HTTP same-host enforcement and auth-header attachment,
- service-specific upstream clients,
- upstream authentication failure state,
- denial of writes when access is read-only.

The core callable layer owns:

- callable schema validation,
- app/local dependency checks through the runtime,
- app context injection,
- file ref resolution,
- converting inline/file outputs into structured results,
- effect summaries,
- callable logs and call tree attribution,
- mapping broker failures into app-router-friendly errors.

## Drive Upload Callable

`omnideck.drive.upload_file@1` wraps the existing Drive broker upload verb and
accepts a runtime file ref instead of a raw path:

```json
{
  "integration_alias": "drive_backup",
  "file_ref": "file:app-export:exp_abc123",
  "name": "project-backlog-backup.json",
  "parent_id": "drive_folder_id_or_null"
}
```

Return:

```json
{
  "file": {
    "id": "1abc...",
    "name": "project-backlog-backup.json",
    "mime_type": "application/json",
    "web_link": "https://drive.google.com/..."
  },
  "size": 18422
}
```

The core wrapper resolves the derived app alias to a connected integration,
resolves the file ref, reads bytes, detects content type, and calls the broker.
The broker owns OAuth credentials, Drive scopes, and write permission
enforcement. The caller cannot choose a raw `integration_id`, raw account id, or
integration that was not derived from the app's callable dependencies.

The existing agent tool may keep accepting a `file_path` argument for user
convenience while internally adapting to the core callable or directly wrapping
the same broker verb during migration.

`@1` is a retained runtime API for saved apps. Breaking changes require a new
version under the lifecycle rules in
[../callable-runtime.md](../callable-runtime.md#core-callable-version-lifecycle).

## Effects

Core integration callable manifests should record broad effects in user-facing
language:

```json
{
  "kind": "drive.write",
  "summary": "Uploads files through connected Drive integrations"
}
```

Runtime logs record concrete effects:

```json
{
  "type": "effect",
  "kind": "drive.write",
  "integration_alias": "drive_backup",
  "resolved_integration_id": "google_workspace",
  "filename": "project-backlog-backup.json",
  "size": 18422,
  "duration_ms": 923
}
```

Effects explain behavior. They are not integration grants.

## Errors

Relevant structured error codes:

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed JSON schema or callable validation |
| `FILE_NOT_FOUND` | File ref is missing or no longer available |
| `FILE_ACCESS_DENIED` | File ref is outside the caller's allowed roots |
| `FILE_TOO_LARGE` | File exceeds upload limit |
| `INTEGRATION_NOT_CONNECTED` | Supervisor has no connected integration |
| `INTEGRATION_PERMISSION_DENIED` | Broker denied capability/access |
| `INTEGRATION_AUTH_FAILED` | Upstream rejected credentials |
| `UPSTREAM_ERROR` | Broker or upstream returned a non-auth transport error |
| `UPSTREAM_TIMEOUT` | Broker request timed out |

The app router should include the callable `call_id` with these errors so the
frontend can show a short message and the agent can inspect logs.

## Backlog Manager Use

For Drive backup, an app callable composes:

```text
omnideck.app.storage.export@1
integration.google_drive.upload_file@1
omnideck.app.storage.update@1
```

If Drive is not connected, unmapped, or lacks write access, the Drive facade
call fails with `INTEGRATION_NOT_CONNECTED` or
`INTEGRATION_PERMISSION_DENIED`.

## Open Decisions

- Whether agent-facing path-based tools should migrate immediately to file refs
  internally or remain direct broker wrappers during the first core callable
  refactor.
- Which existing integration tool should be migrated first after HTTP and Drive
  upload.
- Whether integration wrapper manifests need machine-readable `Capability x
  Access` requirements in addition to human-readable effect summaries.
