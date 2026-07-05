# App Storage Core Callables

> Design for `omnideck.app.storage.*`: app-scoped document storage, query/update
> semantics, app context injection, and backup/export behavior.

## Scope

App storage is durable Omnideck-owned state for one app installation. It is for
data the app needs later, not for temporary files, user-visible downloads, or
external backups.

The first project backlog app needs storage for:

- repository configuration,
- local backlog item records,
- local status/priority/category metadata,
- backup timestamps and sync metadata.

The data belongs to the app. The frontend and app callables do not mutate a
random host path directly.

## Callable Surface

Recommended v1 packages:

| Callable | Purpose | Effects |
|---|---|---|
| `omnideck.app.storage.get@1` | Read one app-scoped document | `app.storage.read` |
| `omnideck.app.storage.list@1` | List/query app-scoped documents | `app.storage.read` |
| `omnideck.app.storage.set@1` | Create or replace one document | `app.storage.write` |
| `omnideck.app.storage.update@1` | Patch one document with revision checks | `app.storage.write` |
| `omnideck.app.storage.delete@1` | Delete one document | `app.storage.write` |
| `omnideck.app.storage.export@1` | Create a backup snapshot file | `app.storage.read`, `file.write` |

Each `@1` version is a retained runtime API for saved apps. Breaking changes
require a new version under the lifecycle rules in
[../callable-runtime.md](../callable-runtime.md#core-callable-version-lifecycle).

## App Context Injection

App callables must not pass their own `app_id`, `app_version`, user id, or
storage root. The callable runtime injects those values into the invocation
context:

```text
caller: app_callable | local_callable | agent
app_id: optional
app_version: optional
call_id: current invocation id
call_stack: dependency call path
```

App-scoped storage callables read app identity only from that context. If there
is no active app context, `omnideck.app.storage.*` fails with
`APP_CONTEXT_REQUIRED`.

When a vendored local callable runs inside a versioned app, it inherits the app
context for that invocation. It may use app storage only if the vendored callable
declares the storage callable as a dependency and the app bundle manifest
includes that transitive core dependency.

The storage scope is the app installation, not a specific app version. A saved
v2 of the same app should see v1 app data unless an explicit migration changes
it. App version remains part of logs, backup metadata, and future migration
checks.

## Storage Model

Use document storage with a key/value shape:

```text
collection: string
id: string
document: JSON object
document_schema_version: app-authored integer
revision: monotonic string
created_at: ISO timestamp
updated_at: ISO timestamp
```

Collections are app-local namespaces such as:

```text
settings
backlog_items
metadata
```

An implementation can start with SQLite under Omnideck state instead of one JSON
file per document. SQLite gives atomic updates, indexed listing, and safer
concurrency than repeated read-modify-write of a large app data file.

Recommended storage root:

```text
{settings.home_dir}/apps/{app_id}/data/
  storage.sqlite
  files/
  exports/
```

The runner process does not open this path directly. Only core storage and file
callables do.

App storage is scoped to the app installation, not to one saved app version. A
rolled-back version can therefore read documents written by a newer version. V1
does not add app-authored migrations, so app manifests should declare
per-collection document schemas and app-authored documents should be
version-tagged. Callables should read tolerantly:

- include a `document_schema_version` field on app-authored documents,
- ignore unknown fields,
- treat newly added fields as optional unless a future migration system says
  otherwise,
- avoid destructive rewrites that older saved app versions cannot read,
- flag storage schema changes in save review as compatibility risk.

This keeps rollback usable without pretending migrations are solved in v1.
If an app omits field-level schemas, schema-change detection is best-effort and
review must say rollback compatibility could not be checked.

## Get

`omnideck.app.storage.get@1` reads one document:

```json
{
  "collection": "backlog_items",
  "id": "item_123"
}
```

Returns:

```json
{
  "found": true,
  "document": {
    "title": "Add issue triage view",
    "status": "todo"
  },
  "revision": "17",
  "created_at": "2026-07-05T18:31:00Z",
  "updated_at": "2026-07-05T18:45:00Z"
}
```

Missing documents return `found: false`; they are not runtime errors.

## Set

`omnideck.app.storage.set@1` creates or replaces a document:

```json
{
  "collection": "backlog_items",
  "id": "item_123",
  "document": {
    "title": "Add issue triage view",
    "status": "todo",
    "priority": "high"
  },
  "if_revision": "16"
}
```

`if_revision` is optional. If present and the current revision differs, the
callable fails with `STORAGE_REVISION_CONFLICT`. This gives app callables a
simple optimistic concurrency primitive.

## Update

`omnideck.app.storage.update@1` applies a constrained patch:

```json
{
  "collection": "backlog_items",
  "id": "item_123",
  "merge": {
    "status": "done",
    "completed_at": "2026-07-05T19:12:00Z"
  },
  "unset": ["blocked_reason"],
  "if_revision": "17"
}
```

Patch semantics are shallow object merge plus top-level unset. Avoid arbitrary
JSONPath mutation in v1. If an app needs deeper changes, it can read, transform,
and set the whole document.

## Delete

`omnideck.app.storage.delete@1` deletes one document and returns whether it
existed. It also accepts `if_revision`.

## List And Query

`omnideck.app.storage.list@1` supports constrained querying:

```json
{
  "collection": "backlog_items",
  "filter": {
    "status": { "eq": "todo" },
    "priority": { "in": ["high", "medium"] }
  },
  "order_by": [
    { "field": "priority_rank", "direction": "asc" },
    { "field": "updated_at", "direction": "desc" }
  ],
  "limit": 100,
  "cursor": null
}
```

Allowed filter operators:

```text
eq
neq
in
lt
lte
gt
gte
exists
```

The storage layer validates field names as simple document keys, not arbitrary
SQL or JSONPath. It returns a cursor for the next page. Limit should have a
small default and hard cap, for example default `100`, max `500`.

This is enough for the backlog manager to list items by status, priority,
category, and updated time. More complex views can be maintained by app logic
using denormalized fields.

## Storage Metadata And Review

An app bundle should declare expected storage collections in its app manifest:

```json
{
  "storage": {
    "collections": {
      "settings": {
        "description": "Repository and app settings",
        "document_schema_version": 1,
        "document_schema": {
          "type": "object",
          "properties": {
            "repository": { "type": "string" },
            "default_status": { "type": "string" }
          },
          "additionalProperties": true
        }
      },
      "backlog_items": {
        "description": "Local backlog items not stored in GitHub",
        "document_schema_version": 1,
        "document_schema": {
          "type": "object",
          "properties": {
            "title": { "type": "string" },
            "status": { "type": "string" },
            "priority": { "type": "string" },
            "updated_at": { "type": "string" }
          },
          "required": ["title"],
          "additionalProperties": true
        }
      },
      "metadata": {
        "description": "Backup timestamps and sync metadata",
        "document_schema_version": 1,
        "document_schema": {
          "type": "object",
          "properties": {
            "last_backup_at": { "type": "string" },
            "last_sync_at": { "type": "string" }
          },
          "additionalProperties": true
        }
      }
    }
  }
}
```

This is review metadata, not an access grant. The app can only touch storage by
invoking declared `omnideck.app.storage.*` dependencies, and the runtime still
injects the app scope.

Import/save review can summarize:

```text
This app stores local data:
- repository and app settings
- local backlog items
- backup and sync metadata
```

## Export And Backup

`omnideck.app.storage.export@1` creates a point-in-time snapshot:

```json
{
  "collections": ["settings", "backlog_items", "metadata"],
  "format": "json",
  "filename": "project-backlog-backup.json"
}
```

Returns:

```json
{
  "file_ref": "file:app-export:exp_abc123",
  "filename": "project-backlog-backup.json",
  "content_type": "application/json",
  "size": 18422,
  "sha256": "..."
}
```

The export should include:

- app id and active app version,
- export timestamp,
- storage schema/review metadata from the app manifest,
- selected collections and documents,
- document revisions and timestamps.

The export should not include integration credentials, broker metadata, callable
runner environments, or callable logs unless explicitly requested by a separate
support-bundle flow.

For Drive backup, an app callable composes:

```text
omnideck.app.storage.export@1
integration.google_drive.upload_file@1
omnideck.app.storage.update@1
```

That keeps storage export and external upload as separate effects in logs and
review summaries.

## Errors

Relevant structured error codes:

| Code | Meaning |
|---|---|
| `APP_CONTEXT_REQUIRED` | App-scoped callable invoked without app context |
| `VALIDATION_ERROR` | Input failed JSON schema or callable validation |
| `STORAGE_NOT_FOUND` | Required storage document does not exist |
| `STORAGE_REVISION_CONFLICT` | `if_revision` did not match current revision |
| `FILE_TOO_LARGE` | Export file exceeds configured limit |

The app router should include the callable `call_id` with these errors so the
frontend can show a short message and the agent can inspect logs.

## Open Decisions

- Whether storage v1 should expose only document operations or also a
  `batch`/transaction callable.
- Whether app storage should support app-authored migrations in v1 or defer
  migrations until app versioning is implemented.
- Whether query indexes are inferred from observed queries, declared in the app
  manifest, or both.
