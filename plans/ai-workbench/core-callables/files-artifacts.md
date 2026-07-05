# File And Artifact Core Callables

> Design for `omnideck.file.*` and future `omnideck.artifact.*`: file refs,
> allowed roots, scratch/app/export storage, and the future path to
> user-visible artifact promotion.

## Scope

Local/app callables should not exchange arbitrary host paths. Core file
callables provide managed file refs for internal composition, such as creating a
storage export and then uploading it to Drive.

User uploads into apps and app-created downloadable artifacts are not required
for v1. This design keeps the future path clear without forcing the app router
to expose input refs or artifact/download refs now.

The lifecycle is:

```text
managed invocation file
  -> app persistent file, if the app needs it later
  -> app export file, if it is a backup/export payload
  -> integration upload, if it should leave Omnideck
  -> artifact, in a later app-facing version if the user should download/keep it
```

## Callable Surface

Recommended v1 packages:

| Callable | Purpose | Effects |
|---|---|---|
| `omnideck.file.read@1` | Read a runtime-owned file reference | `file.read` |
| `omnideck.file.write@1` | Create a runtime-owned file reference | `file.write` |

Deferred app-facing package:

| Callable | Purpose | Effects |
|---|---|---|
| `omnideck.artifact.create@1` | Promote a file reference to a user-visible artifact | `artifact.write` |

Each `@1` version is a retained runtime API for saved apps. Breaking changes
require a new version under the lifecycle rules in
[../callable-runtime.md](../callable-runtime.md#core-callable-version-lifecycle).

## File References

Core file and integration callables should exchange opaque file references:

```text
file:invocation:call_abc123/report.json
file:app-data:app_123/backup-template.json
file:app-export:exp_abc123
file:artifact:art_abc123
file:bundle:apps/app_123/versions/3/assets/logo.png
```

The exact string format can change; callers should treat it as opaque. The
runtime resolves refs to concrete paths only inside trusted core code.

File refs carry metadata:

```json
{
  "file_ref": "file:app-export:exp_abc123",
  "filename": "project-backlog-backup.json",
  "content_type": "application/json",
  "size": 18422,
  "sha256": "..."
}
```

## Scratch Domains And Large-File Handoff

There are two distinct scratch concepts:

- Runner OS scratch. A private writable directory owned by the app-specific
  runner uid and visible only to that runner process. It is for ordinary
  temporary files while callable code runs.
- Managed invocation file refs. Runtime-owned files tracked by core file
  callables and represented as opaque `file_ref` values.

A callable's durable or cross-call outputs leave the runner only through core
file callables. Small payloads can be passed inline to `omnideck.file.write@1`
as `text`, `json`, or `data_b64`, subject to runtime JSON size caps. Larger
payloads cross the runner/`omnideck` boundary through an explicit spool handoff.
Mechanically, the parent opens an Omnideck-owned managed file and passes only
the open write descriptor to the runner across fork/setuid/exec or via
`SCM_RIGHTS` on the inherited control socket. The runner streams bytes into that
descriptor. The parent/core file layer stores the bytes in a managed invocation
file area and returns a `file_ref`.

The runner never hands a host path to a core callable. The parent records the
resulting file metadata, enforces size limits while spooling, and deletes
unpromoted invocation files during runtime cleanup. This qualifies the ordinary
"private scratch" rule: runner OS scratch remains private, but large outputs use
an explicit inherited descriptor controlled by the parent.

The normative launcher and descriptor handoff mechanism lives in
[../callable-runtime.md](../callable-runtime.md#dedicated-runner-user). This
document defines the file callable semantics around the managed refs produced by
that handoff.

## File Roots And Access

Allowed read roots for app callables through `omnideck.file.read@1`:

- read-only app bundle files for the active app version,
- files created in the current managed invocation file area,
- files in the app's persistent file store,
- files returned by core callables in the current call graph,
- future artifact refs explicitly passed to the app by a trusted Omnideck
  surface.

Allowed write roots:

- current managed invocation file area,
- app persistent file store,
- app export area,
- future artifact creation area managed by `omnideck.artifact.create@1`.

Disallowed:

- arbitrary absolute paths,
- parent-directory traversal,
- direct reads from `settings.home_dir`,
- direct reads from integration credential stores,
- direct reads from another app's data,
- direct reads from another invocation's managed files unless promoted to a
  persistent app file or artifact.

For the agent-facing tools that still accept host paths today, the binding can
keep the existing UX. Underneath, the core callable surface should move toward
file refs for app/local callable code.

## Write

`omnideck.file.write@1` creates a managed file:

```json
{
  "scope": "invocation",
  "filename": "github-issues.json",
  "content_type": "application/json",
  "text": "{...}"
}
```

Alternative payload fields:

```text
text
json
data_b64
spool_descriptor
source_file_ref
```

Only one payload field may be present. `scope` can be:

```text
invocation
app_file
app_export
```

Returns file metadata including `file_ref`. The callable enforces size caps,
normalizes filenames, and never accepts arbitrary host paths. `spool_descriptor`
is not a path; it is a parent-issued capability for the current invocation only.

## Read

`omnideck.file.read@1` reads a managed file:

```json
{
  "file_ref": "file:app-export:exp_abc123",
  "max_bytes": 65536,
  "encoding": "utf-8"
}
```

For textual content under `max_bytes`, it can return `text`. For binary or
large content, it returns metadata and requires the caller to pass the `file_ref`
to another callable such as Drive upload. This avoids shoving backup archives or
binary downloads into app callable memory.

## App Outputs And Artifact Ownership

Apps may generate documents, exports, reports, images, archives, and other files
for the user. They may not choose arbitrary host paths outside app/runtime-owned
roots.

The important boundary is ownership:

| Location | Owner | Purpose | Lifetime |
|---|---|---|---|
| Managed invocation files | runtime | temporary intermediate work represented as `file_ref` values | deleted with invocation/runtime cleanup |
| App storage/app files | app | durable internal app state | deleted or exported with app data |
| App exports | app/runtime | backup payloads ready for download/upload | retained by app export policy |
| Artifacts | user | user-visible outputs | survive app deletion unless user chooses otherwise |
| Drive/docs uploads | external account | files outside Omnideck | controlled by the integration service |

An app-created JSON backup starts as a `file_ref`. In v1 it can leave Omnideck
through an integration facade such as `integration.google_drive.upload_file@1`. In a
later app-facing version it can become user-visible when an app callable invokes
`omnideck.artifact.create@1`.

If app-created artifacts are added later, deleting an app should not silently
delete promoted artifacts. Artifacts are outputs the user has received from the
app, not app-private state. If the app manager offers deletion of app outputs,
it should be an explicit user choice with a reviewable list/count of affected
artifacts.

## Relationship To Current Artifacts

Current artifacts are indexed from `file_output` events and keyed by
conversation plus path. If app-created artifacts are added later, they should
evolve the shared artifact model toward:

```text
artifact_id
file_ref
filename
content_type
size
sha256
provenance
created_at
updated_at
```

Provenance should support multiple source types:

```json
{
  "kind": "app",
  "app_id": "app_project_backlog",
  "app_version": "3",
  "call_id": "call_abc123",
  "callable_id": "app.backup_project@1"
}
```

Conversation-created artifacts can keep conversation provenance:

```json
{
  "kind": "conversation",
  "conversation_id": "conv_abc123",
  "agent_name": "Omnideck"
}
```

The user-facing artifact hub should stay shared. Future app-created artifacts
should appear in the same artifact/download surfaces as agent-created artifacts,
with app provenance shown where useful. A parallel app-only artifact store would
make outputs harder to find and would blur the ownership distinction between app
state and user-owned outputs.

If the router later returns app-created artifacts, app frontends should receive
artifact or download handles, never host paths:

```json
{
  "artifact_id": "art_abc123",
  "download_ref": "download:artifact:art_abc123"
}
```

The frontend can pass that handle back to Omnideck download/preview APIs or show
it in the app UI. It cannot resolve the handle into a path or use it to browse
nearby files.

If the router later accepts user-selected app input files, apps may consume
artifact/file refs only when Omnideck or the user explicitly passes them in,
such as through a file picker, drag/drop upload, "open with app" flow, or a
callable result from the current app. Apps should not be able to list or read
every artifact by default. A selected artifact ref is a scoped input to that app
action, not a grant to the whole artifact catalog.

## Create Artifact

If app-created artifacts are added later, `omnideck.artifact.create@1` promotes
a file ref:

```json
{
  "file_ref": "file:app-export:exp_abc123",
  "title": "Project backlog backup",
  "filename": "project-backlog-backup.json"
}
```

Returns:

```json
{
  "artifact_id": "art_abc123",
  "file_ref": "file:artifact:art_abc123",
  "filename": "project-backlog-backup.json",
  "content_type": "application/json",
  "size": 18422
}
```

The callable should:

- copy or link the source file into an artifact-managed root,
- emit/index artifact metadata with source type, app id, app version, call id,
  and source callable when present,
- make the file available through the existing artifact/download UI,
- avoid exposing raw host paths to the app frontend.

Creating an artifact is separate from uploading to Drive. Some workflows may
need a download only, some may need Drive only, and some may need both.

## Errors

Relevant structured error codes:

| Code | Meaning |
|---|---|
| `VALIDATION_ERROR` | Input failed JSON schema or callable validation |
| `FILE_NOT_FOUND` | File ref is missing or no longer available |
| `FILE_ACCESS_DENIED` | File ref is outside the caller's allowed roots |
| `FILE_TOO_LARGE` | File exceeds callable limit |

The app router should include the callable `call_id` with these errors so the
frontend can show a short message and the agent can inspect logs.

## Open Decisions

- Exact file ref format and whether refs are signed, database-backed opaque ids,
  or both.
- Exact migration path from today's conversation/path artifact index to
  file-ref-backed artifacts with source provenance.
- Whether frontend-safe download refs are served by direct HTTP routes or only
  by a parent bridge in the sandboxed-frame model.
- Whether app-created artifacts and user-selected app input files are needed in
  v2, and what concrete user workflows require them.
