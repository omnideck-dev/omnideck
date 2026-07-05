# Core Callables

> Index and shared contract for the first Omnideck-owned callable surface that
> app and local callables use for storage, internal file/export handling,
> HTTP/API calls, and integration-backed effects.

## Relationship To Callable Runtime

[callable-runtime.md](callable-runtime.md) defines how core, local, and app
callables are packaged, resolved, invoked, isolated, and logged. This document
summarizes the first useful core callables those isolated runners can call.

The guiding rule is the same as the runtime design: useful work should go
through declared callable dependencies and parent-managed invocation, not broad
ambient access from a runner process.

Examples from the runtime:

```text
omnideck.file.read@1
omnideck.file.write@1
omnideck.http.fetch@1
omnideck.http.request@1
omnideck.app.storage.get@1
omnideck.app.storage.set@1
omnideck.drive.upload_file@1
```

The first surface should support the project backlog app use case:

- app-local backlog data and settings,
- export/backup file creation,
- HTTP/API calls for GitHub-style integrations,
- public no-auth reads from approved web hosts,
- Drive upload through an already connected integration.

User uploads into apps and app-created downloadable artifacts are not required
for v1. The file/artifact design keeps enough structure to add those later
without exposing host paths or changing the app router shape.

## Category Designs

The detailed designs are split by core callable category:

| Category | Design | Core callables |
|---|---|---|
| App storage | [core-callables/app-storage.md](core-callables/app-storage.md) | `omnideck.app.storage.*@1` |
| Files and artifacts | [core-callables/files-artifacts.md](core-callables/files-artifacts.md) | `omnideck.file.*@1`; `omnideck.artifact.create@1` is deferred for app-facing v1 |
| Public HTTP fetch | [core-callables/http-fetch.md](core-callables/http-fetch.md) | `omnideck.http.fetch@1` |
| HTTP/API requests | [core-callables/http-request.md](core-callables/http-request.md) | `omnideck.http.request@1` |
| Integration wrappers | [core-callables/integration-wrappers.md](core-callables/integration-wrappers.md) | `omnideck.drive.upload_file@1`, future broker-backed wrappers |

Keep this file as the overview. Put callable-specific schema, behavior, error,
logging, and open-decision detail in the category files.

## Design Goals

- Make app callables useful without giving them host filesystem, network, or
  credential access.
- Treat every core callable as a privileged trust boundary. Core callables run
  as trusted Omnideck code on input that may originate from untrusted local/app
  callable code.
- Keep app storage owned by Omnideck and scoped to the app, not to arbitrary
  paths the frontend can mutate directly.
- Return structured results and structured errors suitable for the app router.
- Preserve the existing broker permission model. Core callables do not grant or
  deny Gmail, Drive, HTTP, or other external capabilities independently.
- Produce effect metadata for import/save review, runtime logs, and agent
  debugging.
- Keep the v1 API small enough that app callables can compose higher-level
  behavior themselves.

## Non-Goals

- Arbitrary app-defined HTTP routes. The app router still invokes public app
  callables only.
- A second integration permission system above the supervisor and broker.
- Direct credential access from local/app callable runners.
- A general host filesystem API for app code.
- Broad ambient-power callables, such as a general "run shell command" callable
  or a generic host filesystem escape.
- A full database product exposed to app code. App storage starts as
  document/key-value storage with constrained query semantics.
- User file uploads into apps for v1.
- App-created downloadable artifacts for v1.

## Core Surface Summary

Recommended v1 core packages:

| Callable | Purpose | Effects | Design |
|---|---|---|---|
| `omnideck.app.storage.get@1` | Read one app-scoped document | `app.storage.read` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.app.storage.list@1` | List/query app-scoped documents | `app.storage.read` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.app.storage.set@1` | Create or replace one document | `app.storage.write` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.app.storage.update@1` | Patch one document with revision checks | `app.storage.write` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.app.storage.delete@1` | Delete one document | `app.storage.write` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.app.storage.export@1` | Create a backup snapshot file | `app.storage.read`, `file.write` | [app-storage.md](core-callables/app-storage.md) |
| `omnideck.file.read@1` | Read a runtime-owned file reference | `file.read` | [files-artifacts.md](core-callables/files-artifacts.md) |
| `omnideck.file.write@1` | Create a runtime-owned file reference | `file.write` | [files-artifacts.md](core-callables/files-artifacts.md) |
| `omnideck.artifact.create@1` | Promote a file reference to a user-visible artifact | `artifact.write` | [files-artifacts.md](core-callables/files-artifacts.md); deferred for app-facing v1 |
| `omnideck.http.fetch@1` | Fetch public unauthenticated HTTP data from app-approved hosts | `http.read` | [http-fetch.md](core-callables/http-fetch.md) |
| `omnideck.http.request@1` | Make an authenticated HTTP/API request through an integration | `http.read` or `http.write` | [http-request.md](core-callables/http-request.md) |
| `omnideck.drive.upload_file@1` | Upload a runtime file through a Drive integration | `drive.write` | [integration-wrappers.md](core-callables/integration-wrappers.md) |

The actual packages live under the core callable root described in
[callable-runtime.md](callable-runtime.md#manifest-shape):

```text
callables/core/omnideck.app.storage.get/
  manifest.json
callables/core/omnideck.http.request/
  manifest.json
```

Core callable implementations may remain Python import targets that wrap
existing server, artifact, and integration code.

Agent app-building discovery may expose connected integrations as integration
facade callables, such as `integration.github.request@1` or
`integration.google_drive.upload_file@1`. Those facades are catalog entries and
saved-app integration uses; the backing privileged implementations remain core
callables such as `omnideck.http.request@1` and
`omnideck.drive.upload_file@1`.

Because core callables are privilege boundaries, each implementation must
validate inputs as hostile even when the calling app was user-built locally. Do
not rely on app callable manifests, frontend code, or agent-authored code for
safety. A single over-broad or under-validated core callable can undo the runner
isolation model.

Each listed `@1` version is a retained runtime API for saved apps. Breaking
changes to schemas, error codes, file-ref semantics, storage behavior, or effect
meaning require a new `@2` callable while `@1` remains available for app
versions that already depend on it. The lifecycle rules live in
[callable-runtime.md](callable-runtime.md#core-callable-version-lifecycle).

## Shared Result And Error Shape

Core callables should use the runtime's structured result and error envelopes.
The app router includes the callable `call_id` alongside structured errors so
the frontend can show a short message and the agent can inspect logs.

Common error codes across core callable categories:

| Code | Meaning |
|---|---|
| `APP_CONTEXT_REQUIRED` | App-scoped callable invoked without app context |
| `VALIDATION_ERROR` | Input failed JSON schema or callable validation |
| `CORE_CALLABLE_DISABLED` | A retained core callable version is disabled for security reasons |
| `STORAGE_NOT_FOUND` | Required storage document does not exist |
| `STORAGE_REVISION_CONFLICT` | `if_revision` did not match current revision |
| `FILE_NOT_FOUND` | File ref is missing or no longer available |
| `FILE_ACCESS_DENIED` | File ref is outside the caller's allowed roots |
| `FILE_TOO_LARGE` | File exceeds callable limit |
| `INTEGRATION_NOT_CONNECTED` | Supervisor has no connected integration |
| `INTEGRATION_PERMISSION_DENIED` | Broker denied capability/access |
| `INTEGRATION_AUTH_FAILED` | Upstream rejected credentials |
| `UPSTREAM_ERROR` | Broker or upstream returned a non-auth transport error |
| `UPSTREAM_TIMEOUT` | Broker request timed out |
| `RESPONSE_TOO_LARGE` | HTTP response exceeded configured limit |

Each category doc lists the subset relevant to that callable family.

## Shared Logs And Effect Summaries

Every core callable invocation should emit sanitized structured events into the
callable run log. Do not log credentials, auth headers, request bodies by
default, full response bodies, or raw host paths.

App import/save review derives user-facing effects from the transitive set of
declared callable dependencies and the effect metadata on the resolved core
callables. Author-written summary text in an app manifest may be shown as
documentation, but it is not the basis for security review because an imported
app can understate what it does.

Effect-kind mapping for v1 review:

| Effect kind | Review sentence |
|---|---|
| `app.storage.read` | read app-local storage |
| `app.storage.write` | write app-local storage |
| `file.read` | read app/runtime-managed files |
| `file.write` | create app/runtime-managed files |
| `http.read` | make read requests through connected HTTP/API integrations or approved public web hosts |
| `http.write` | make write requests through connected HTTP/API integrations |
| `drive.write` | upload files through connected Drive integrations |
| `artifact.write` | create user-visible artifacts |

Review should deduplicate and group related effects, but it must not omit an
effect kind present in the transitive core dependency set.

```text
This app may:
- read and write app-local storage
- create app/runtime-managed files
- make read requests to approved public web hosts
- make read and write requests through connected HTTP/API integrations
- upload files through connected Drive integrations
```

If the app or its vendored callables need packages outside the runtime baseline,
review should also show the long-tail package approval request:

```text
This app wants to install extra packages:
- pypdf==4.3.1
- rapidfuzz==3.9.6
```

Approving extra packages is separate from approving integration effects.
Installing packages runs package code, so extra packages require explicit user
approval before save/import prepares the runtime environment.

Future placeholder: add an LLM core callable family so app/local callables can
classify, summarize, and generate through Omnideck models without direct
provider credentials. This is intentionally not designed in the first core
surface, but discovery and package guidance should leave room for it.

Runtime logs use concrete invocation summaries:

```text
app.backup_project created project-backlog-backup.json, then uploaded it to
Drive through google_workspace.
```

These summaries explain behavior. They are not grants.

## Backlog Manager Flow

One public app callable can implement "Back up project":

```text
app.backup_project@1
  -> omnideck.app.storage.export@1          # create backup snapshot file_ref
  -> integration.google_drive.upload_file@1 # upload backup through mapped Drive account
  -> omnideck.app.storage.update@1          # store last backup metadata
```

If Drive is not connected or lacks write access, the Drive core callable fails
with `INTEGRATION_NOT_CONNECTED` or `INTEGRATION_PERMISSION_DENIED`.

## Cross-Cutting Open Decisions

- Whether category docs should eventually become manifest-adjacent
  implementation specs under `callables/core/*`.
- Whether shared effect metadata should be represented only in manifests or also
  in generated developer docs.
- How much sanitized effect detail the app router should return by default.
- Whether app-created artifacts and user-selected app input files become v2
  router features.
