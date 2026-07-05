# Agent Build Tooling

> Tool contracts and workflow for letting the Omnideck agent build app drafts
> with normal source files, register app actions from code, test backend actions,
> and hand user-owned save/export/rollback decisions to trusted UI.

## Relationship To Other Designs

[callable-runtime.md](callable-runtime.md) defines callable packaging,
execution, dependency calls, logs, and schema derivation.
[core-callables.md](core-callables.md) defines the core capability surface.
[bundle-format.md](bundle-format.md) defines saved app versions and the
compiled manifest. [app-router.md](app-router.md) defines saved-app invocation.
[frontend-runtime.md](frontend-runtime.md) defines the live builder/app frame.
[feature-flags.md](feature-flags.md) defines release gates.

This document owns only the agent-facing app-building tools. It does not define
normal filesystem editing tools. The agent uses its existing file tools to write
HTML, CSS, JavaScript, Python, tests, and supporting files.

## Core Model

An app draft is a working tree plus tool-owned registrations:

```text
app draft working tree
  frontend/
    index.html
    assets/
  actions/
    backlog.py
  tests/

tool-owned app state
  app metadata
  frontend folder pointer
  app callable registrations
  storage collection declarations
  web_allowlist declarations
  derived integration uses
```

The agent authors program files. The app tools own the app/callable folder
structure, registrations, generated callable manifests, and saved bundle
manifest. The agent never hand-writes the app manifest.

Drafts are compiled at save. Save is a trusted user action that reads the
working tree plus registrations, derives schemas, validates dependencies,
vendors local callable dependencies, records exact package locks, computes
hashes, derives review summaries, and writes an immutable saved app version.

The live builder is a shell surface, not an agent tool. Entering app mode opens
or focuses the builder UI with chat, a sandboxed live app frame, review state,
and a shared run log. The user can interact with the draft while the agent edits
files. The draft may be temporarily broken during construction.

All tools in this document are gated by `ai_workbench.enabled` and
`ai_workbench.builder_enabled`. Tools must return `FEATURE_DISABLED` if called
while disabled. `app_test` also requires `ai_workbench.runtime_enabled` because
it can launch app runners.

## Tool Surface

The v1 app-building tool family is:

| Tool | Purpose |
|---|---|
| `edit_app` | Start a new app or open an existing app draft; opens/focuses the live builder |
| `app_callable_catalog` | List callable dependencies, integration callable facades, and package availability |
| `app_add_callable` | Register a Python function file as an app callable; derive schema from code |
| `app_set_frontend` | Point the app at a static frontend folder and entry file |
| `app_configure` | Set app-level declarations: storage collections and `web_allowlist` |
| `app_test` | Run any registered app callable, public or private, with args |
| `app_get_run` | Read the shared run record for an agent test or user-triggered preview run |

Removed from this surface:

- per-file app tools such as `apps.write_draft_file`; use the agent's existing
  file tools,
- per-field manifest mutation tools; the tools own manifests,
- separate preview start/invoke tools; the live builder owns preview,
- save/export/rollback/support-bundle tools; these are user actions,
- local-callable authoring; that is a separate tool surface.

## Common Envelope

All app build tools reject unknown top-level request fields with
`VALIDATION_ERROR`.

Failure envelope:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable explanation safe to show to the agent.",
    "retryable": false,
    "details": {}
  }
}
```

Common error codes:

| Code | Meaning |
|---|---|
| `FEATURE_DISABLED` | App building or runtime testing is disabled |
| `VALIDATION_ERROR` | Request shape or value is invalid |
| `APP_NOT_FOUND` | App id does not exist or is not visible |
| `DRAFT_NOT_FOUND` | Draft id does not exist or is not visible |
| `PATH_NOT_FOUND` | Source path or frontend entry does not exist |
| `PATH_NOT_ALLOWED` | Path escapes the draft working tree |
| `FRONTEND_INVALID` | Frontend folder cannot be served as a v1 static app |
| `CALLABLE_NOT_FOUND` | Callable route is not registered |
| `CALLABLE_SCHEMA_INVALID` | Schema could not be derived from the registered function |
| `CALLABLE_DEPENDENCY_MISSING` | A declared dependency is unavailable |
| `PACKAGE_APPROVAL_REQUIRED` | Extra packages need user approval before execution/save |
| `INTEGRATION_ACCOUNT_REQUIRED` | User must map an integration use to a connected account |
| `LIVE_EFFECT_APPROVAL_REQUIRED` | Live external effects require user approval |
| `CALLABLE_RUNTIME_ERROR` | Runner crashed or returned an invalid runtime frame |
| `TOOL_INTERNAL_ERROR` | Unexpected implementation failure |

Opaque ids such as `app_id`, `draft_id`, `builder_session_id`, and `call_id`
are minted by Omnideck.

## `edit_app`

Starts app mode. If `app_id` is omitted, Omnideck creates a new draft app. If
`app_id` is present, Omnideck opens the existing draft or creates a draft from
the active saved version when `from_active_version` is true.

Request:

```json
{
  "app_id": null,
  "title": "Project Backlog",
  "from_active_version": false
}
```

Response:

```json
{
  "ok": true,
  "app_id": "app_project_backlog",
  "draft_id": "draft_123",
  "working_tree_root": "apps/app_project_backlog/drafts/draft_123/",
  "builder_session_id": "builder_789",
  "builder_url": "/apps/app_project_backlog/build",
  "status": "draft"
}
```

The returned root is a workspace-relative editing root for the agent's existing
file tools, not a host filesystem grant to app code.

## `app_callable_catalog`

Returns what the draft may depend on: core callables, integration callable
facades backed by connected integration types, local callables available for
vendoring, and package availability.

Request:

```json
{
  "draft_id": "draft_123",
  "include_core": true,
  "include_integrations": true,
  "include_local": true,
  "include_packages": true
}
```

Response:

```json
{
  "ok": true,
  "core_callables": [
    {
      "ref": "omnideck.app.storage.list@1",
      "title": "List app storage documents",
      "effects": ["app.storage.read"],
      "input_schema": {},
      "output_schema": {}
    }
  ],
  "integration_callables": [
    {
      "ref": "integration.github.request@1",
      "title": "GitHub API request",
      "provider": "github",
      "kind": "http",
      "access": "read_write",
      "backing_core_callable": "omnideck.http.request@1",
      "suggested_alias": "github",
      "connected_account_count": 1,
      "effects": ["http.read", "http.write"],
      "input_schema": {},
      "output_schema": {}
    },
    {
      "ref": "integration.google_drive.upload_file@1",
      "title": "Upload file to Google Drive",
      "provider": "google_drive",
      "kind": "drive",
      "access": "write",
      "backing_core_callable": "omnideck.drive.upload_file@1",
      "suggested_alias": "drive_backup",
      "connected_account_count": 2,
      "effects": ["drive.write"],
      "input_schema": {},
      "output_schema": {}
    }
  ],
  "local_callables": [],
  "packages": {
    "python": {
      "baseline_packages": ["python-dateutil==2.9.0.post0"],
      "approved_extra_packages": []
    }
  }
}
```

Integration entries are callable facades. The agent depends on them like any
other callable. The catalog may show provider, kind, access, and whether
matching connected accounts exist, but it must not expose credentials, tokens,
refresh state, or account secrets.

The agent does not author integration configuration. When the agent registers a
callable that depends on an integration facade, Omnideck records a derived app
integration use under an app-level alias. The user later maps that alias to a
connected account in trusted UI.

## `app_add_callable`

Registers a Python function as an app callable. The source file already exists
because the agent wrote it with normal file tools.

Request:

```json
{
  "draft_id": "draft_123",
  "route": "sync_github",
  "source_path": "actions/github_sync.py",
  "function": "sync_github",
  "app_visibility": "public",
  "dependencies": [
    {
      "ref": "omnideck.app.storage.list@1"
    },
    {
      "ref": "integration.github.request@1",
      "alias": "github"
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "route": "sync_github",
  "callable_id": "app.sync_github",
  "app_visibility": "public",
  "input_schema": {
    "type": "object",
    "properties": {
      "repository": { "type": "string" }
    },
    "required": ["repository"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "synced": { "type": "integer" }
    },
    "required": ["synced"]
  },
  "registered_dependencies": [
    "omnideck.app.storage.list@1",
    "integration.github.request@1"
  ],
  "derived_integration_uses": [
    {
      "alias": "github",
      "ref": "integration.github.request@1",
      "provider": "github",
      "kind": "http",
      "access": "read_write",
      "backing_core_callable": "omnideck.http.request@1"
    }
  ]
}
```

`route` is the public/internal app action name. It must match the app router's
route-name rule. `app_visibility` is `public` or `private`.

Schema derivation is mandatory for v1. The registered function must have typed
parameters, a typed return value, and a docstring. Omnideck derives JSON schemas
from the function signature, type hints, and docstring using the same
callable-to-schema machinery used for existing tools. If schema derivation is
ambiguous, registration fails with `CALLABLE_SCHEMA_INVALID`; the agent fixes
the function types/docstring and calls `app_add_callable` again.

The tool is idempotent by `draft_id + route`. Re-registering the same route
updates the source path, function name, visibility, dependencies, derived
schemas, generated callable manifest, and derived integration uses.

Integration dependency aliases:

- are app-level names such as `github` or `drive_backup`,
- must be unique within the app,
- are written by the tool into derived app state, not by the agent into a
  manifest,
- become install/runtime account-mapping keys,
- are not raw connected integration ids.

App code should invoke the declared dependency name exposed by the runtime, not
hard-code connected account ids. For an integration facade dependency, the
runtime resolves the alias to the user-selected connected account and then calls
the backing core callable.

## `app_set_frontend`

Registers the static frontend folder for the draft. The agent writes all files
with normal file tools before calling this tool.

Request:

```json
{
  "draft_id": "draft_123",
  "folder": "frontend/",
  "entry": "index.html"
}
```

Response:

```json
{
  "ok": true,
  "folder": "frontend/",
  "entry": "index.html",
  "servable_entry": "frontend/index.html",
  "warnings": []
}
```

Rules:

- `folder` must be inside the draft working tree.
- `entry` must be an HTML file under `folder`.
- Relative asset paths are allowed only when they stay inside `folder`.
- The frontend must satisfy v1 frame/CSP constraints: no remote scripts, no
  service worker registration, no browser network dependency, and no raw
  Omnideck API calls.

The saved bundle stores the folder contents under `frontend/` and serves the
entry through the parent-controlled frame document.

## `app_configure`

Sets app-level declarations that cannot be inferred from one callable function:
storage collections and public web hosts.

Request:

```json
{
  "draft_id": "draft_123",
  "storage_collections": {
    "backlog_items": {
      "description": "Local backlog items not stored in GitHub",
      "document_schema": {
        "type": "object",
        "properties": {
          "title": { "type": "string" },
          "status": { "type": "string" }
        },
        "required": ["title"],
        "additionalProperties": true
      }
    }
  },
  "web_allowlist": [
    {
      "host": "status.example.com",
      "purpose": "Read the public service status feed"
    }
  ]
}
```

Response:

```json
{
  "ok": true,
  "storage_collections": ["backlog_items"],
  "web_allowlist": ["status.example.com"],
  "review_items": [
    "stores local backlog items",
    "may fetch or display public web data from status.example.com"
  ]
}
```

`web_allowlist` is reviewed at save/import and is also gated by
`ai_workbench.public_fetch_enabled`.

## `app_test`

Runs any registered callable in the draft, public or private. This is the
agent's backend test loop. The live builder is the UI preview loop; there is no
separate preview invocation tool.

Request:

```json
{
  "draft_id": "draft_123",
  "route": "sync_github",
  "args": {
    "repository": "owner/repo"
  },
  "mode": "dry_run"
}
```

`mode` is `dry_run` or `live`. External-effect integration facades and
broker-backed core callables run in dry-run mode unless trusted UI has recorded
live-effect approval for the current user, draft, route, dependency alias, and
builder session.

Response:

```json
{
  "ok": true,
  "call_id": "call_abc123",
  "route": "sync_github",
  "mode": "dry_run",
  "result": {
    "synced": 12
  },
  "effects": [
    {
      "kind": "http.read",
      "summary": "Would read GitHub issues through github"
    }
  ]
}
```

If user account mapping is missing for an integration alias, return
`INTEGRATION_ACCOUNT_REQUIRED` with details:

```json
{
  "ok": false,
  "call_id": "call_abc123",
  "error": {
    "code": "INTEGRATION_ACCOUNT_REQUIRED",
    "message": "Choose a GitHub account for this app before running sync_github live.",
    "retryable": true,
    "details": {
      "alias": "github",
      "provider": "github",
      "kind": "http",
      "access": "read_write"
    }
  }
}
```

## `app_get_run`

Reads the shared run record for agent tests and user-triggered builder preview
runs. The live builder and the agent look at the same run ids.

Request:

```json
{
  "call_id": "call_abc123"
}
```

Response:

```json
{
  "ok": true,
  "call_id": "call_abc123",
  "app_id": "app_project_backlog",
  "draft_id": "draft_123",
  "route": "sync_github",
  "status": "failed",
  "started_at": "2026-07-05T20:10:00Z",
  "duration_ms": 412,
  "error": {
    "code": "INTEGRATION_ACCOUNT_REQUIRED",
    "message": "Choose a GitHub account for this app before running sync_github live."
  },
  "events": [
    {
      "type": "effect",
      "kind": "http.read",
      "summary": "Would read GitHub issues through github"
    }
  ],
  "stdout_excerpt": "",
  "stderr_excerpt": ""
}
```

Run records are sanitized. They must not include credentials, raw host paths,
full request/response bodies, or package install logs beyond bounded excerpts.

## Integration Uses And Account Mapping

Integration use is derived from callable dependencies, not from an
agent-authored manifest section.

Example dependency:

```json
{
  "ref": "integration.github.request@1",
  "alias": "github"
}
```

The tool records this derived app integration use:

```json
{
  "alias": "github",
  "ref": "integration.github.request@1",
  "provider": "github",
  "kind": "http",
  "access": "read_write",
  "backing_core_callable": "omnideck.http.request@1"
}
```

At save/import/install time, trusted UI asks the user to map each alias to a
connected account that satisfies provider/kind/access. Zero matches leave the
alias unconfigured. One match may be suggested but still needs user approval.
Multiple matches require user choice. Exported app bundles never include
another user's connected integration ids.

Typed integration facades such as Drive upload or email send can usually be
matched by provider/kind/access. HTTP integration facades still need the alias
because one app may use multiple HTTP/API services.

## Save Handoff

Save is not an agent tool. Before handing the user to save, the agent can use
the seven-tool surface plus normal file reads to verify:

- frontend folder is registered,
- every app action is registered from code and schema-derived,
- dependencies resolve in the catalog,
- storage collections and `web_allowlist` are configured,
- backend tests pass or known failures are explained,
- extra package approvals are clear,
- integration uses and account mappings are clear.

The user-owned save action compiles the working tree and registrations into the
saved bundle manifest, exact lock files, hashes, vendored local callables, and
review summary.

## Build, Debug, Refine Loop

From the agent's perspective:

```text
edit_app
  -> write frontend and Python files with normal file tools
  -> app_callable_catalog
  -> app_add_callable for each app action/helper
  -> app_set_frontend
  -> app_configure
  -> app_test backend actions in dry_run mode
  -> app_get_run for failures
  -> patch files and re-register changed callables
  -> ask user for live-effect/account/package approval when needed
  -> hand user to trusted save review
```

The user can interact with the live builder throughout this loop. User-triggered
preview runs produce the same `call_id` records that `app_get_run` reads.

## Security Constraints

Agent build tools must preserve the boundaries in the other designs:

- app frontend code runs only in the sandboxed frame,
- frontend invokes backend work only through the parent bridge and app router,
- app callables run only through the callable runtime,
- local/app callable code is never imported into the Omnideck server process,
- packages install only in isolated environment builders,
- app code never receives integration credentials,
- integration facades resolve account mappings server-side,
- external effects go through core callables and the broker,
- saved versions are immutable,
- imported apps require user review.

The agent can explain and repair, but it cannot grant itself broader authority.

## Backlog Manager Flow

1. User asks the agent to build a backlog app for a GitHub repo.
2. Agent calls `edit_app`, which opens the live builder.
3. Agent writes `frontend/index.html`, CSS/JS assets, and Python action files.
4. Agent calls `app_callable_catalog` and sees storage, GitHub request, and
   Drive upload capabilities.
5. Agent registers `list_backlog`, `save_item`, `sync_github`, and
   `backup_project` with `app_add_callable`.
6. Dependencies on `integration.github.request@1` derive the `github` app
   integration use. Dependencies on `integration.google_drive.upload_file@1`
   derive the `drive_backup` app integration use.
7. Agent calls `app_set_frontend` and `app_configure`.
8. Agent runs backend tests with `app_test` in `dry_run` mode and debugs
   failures with `app_get_run`.
9. User maps GitHub/Drive accounts and approves any live preview calls from
   trusted UI.
10. User saves version 1 through trusted UI.

## Open Decisions

- Exact Python type/docstring subset accepted by schema derivation.
- Whether browser-automation smoke checks become an eighth tool or remain
  implementation-owned builder diagnostics.
- Exact live-effect approval UI and expiry rules.
