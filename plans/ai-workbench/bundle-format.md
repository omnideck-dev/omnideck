# Bundle Format

> Detailed design for draft apps, saved app versions, manifests, hashes,
> vendoring, import/export archives, rollback, and app data boundaries.

## Relationship To Other Designs

[callable-runtime.md](callable-runtime.md) defines callable packaging and
runtime resolution. [app-router.md](app-router.md) defines how the active app
version exposes public app callables to the frontend. This document defines the
durable app object those layers read.

The bundle format is the shared contract for:

- the frontend runtime serving app files,
- the callable registry loading app and vendored callables,
- the agent tooling editing draft apps,
- the UX saving, launching, exporting, importing, and rolling back apps.

## Goals

- Make saved apps immutable and rollbackable.
- Make exported apps portable without a package manager.
- Vendor every non-core dependency a saved app needs.
- Pin exact core callable versions.
- Keep app frontend, app callables, vendored callables, and review metadata in
  one manifest.
- Make hash coverage clear enough for tamper evidence and exact rollback.
- Keep app-local data separate from app code/version bundles.

## Non-Goals

- Standalone sharing of local callables outside an app bundle.
- A package-manager-style dependency solver for apps.
- App frontend hosting details such as iframe bridge or CSP.
- User file uploads into apps or app-created downloadable artifacts for v1.
- Bundling integration credentials or broker state.

## App Identity

An app has a stable app id and a mutable active version pointer:

```text
apps/{app_id}/
  app.json
  drafts/
  versions/
  data/
```

`app.json` is small app-level metadata:

```json
{
  "id": "app_project_backlog",
  "title": "Project Backlog",
  "created_at": "2026-07-05T18:00:00Z",
  "updated_at": "2026-07-05T20:00:00Z",
  "active_version": "3",
  "draft_id": "draft_current",
  "created_by": {
    "kind": "agent",
    "conversation_id": "conv_abc123"
  }
}
```

The active version pointer is server-owned state. The app router resolves it
before invoking a public app callable. The frontend does not choose a version in
the normal saved-app route.

## Drafts And Saved Versions

Draft apps are mutable workspaces for the agent. Saved app versions are
immutable bundles.

Drafts may:

- be edited in place,
- reference live local callables while the agent iterates,
- keep transient build/test metadata,
- be previewed through explicit editor/preview routes.

Saved versions must:

- copy frontend files into a version directory,
- copy app callable packages into the version directory,
- vendor selected local callable dependencies,
- record exact core callable dependencies,
- record hashes for bundled files,
- never reach back into the live local callable store.

Recommended storage:

```text
{settings.home_dir}/apps/{app_id}/
  app.json
  drafts/
    draft_current/
      manifest.json
      frontend/
      callables/
      vendor_refs.json
      build/
  versions/
    1/
      manifest.json
      frontend/
      callables/
      vendor/
    2/
      manifest.json
      frontend/
      callables/
      vendor/
  data/
    storage.sqlite
    files/
    exports/
```

Only `versions/{version}/` is served as a saved app. `data/` is app-owned
runtime state, not part of the immutable bundle.

## Directory Layout

Saved version layout:

```text
versions/{version}/
  manifest.json
  frontend/
    index.html
    assets/
      app.js
      app.css
  callables/
    list_backlog/
      manifest.json
      requirements.lock
      implementation.py
    backup_project/
      manifest.json
      requirements.lock
      implementation.py
  vendor/
    local.normalize_issue/
      manifest.json
      requirements.lock
      implementation.py
```

`frontend/` is read-only at runtime. `callables/` contains app-scoped callable
packages. `vendor/` contains copied local callable packages used by this saved
version.

## Manifest Schema

The app version manifest is the source of truth for bundle inventory, callable
visibility, derived integration uses, core dependencies, storage review metadata,
package review metadata, and hash coverage.

Example:

```json
{
  "schema_version": 1,
  "id": "app_project_backlog",
  "version": "3",
  "title": "Project Backlog",
  "created_at": "2026-07-05T20:00:00Z",
  "created_by": {
    "kind": "agent",
    "conversation_id": "conv_abc123"
  },
  "requires": {
    "omnideck_core": ">=1"
  },
  "entrypoint": {
    "html": "frontend/index.html"
  },
  "integration_uses": {
    "github": {
      "ref": "integration.github.request@1",
      "kind": "http",
      "provider": "github",
      "access": "read_write",
      "backing_core_callable": "omnideck.http.request@1",
      "purpose": "Read and close issues for the backlog app"
    },
    "drive_backup": {
      "ref": "integration.google_drive.upload_file@1",
      "kind": "drive",
      "provider": "google_drive",
      "access": "write",
      "backing_core_callable": "omnideck.drive.upload_file@1",
      "purpose": "Upload backup files"
    }
  },
  "web_allowlist": [
    {
      "host": "status.example.com",
      "purpose": "Read the public service status feed"
    }
  ],
  "core_dependencies": [
    "omnideck.app.storage.get@1",
    "omnideck.app.storage.list@1",
    "omnideck.app.storage.set@1",
    "omnideck.app.storage.update@1",
    "omnideck.app.storage.export@1",
    "omnideck.file.write@1",
    "omnideck.http.fetch@1",
    "omnideck.http.request@1",
    "omnideck.drive.upload_file@1"
  ],
  "callables": {
    "list_backlog": {
      "id": "app.list_backlog",
      "version": "1",
      "app_visibility": "public",
      "path": "callables/list_backlog/",
      "sha256": "..."
    },
    "backup_project": {
      "id": "app.backup_project",
      "version": "1",
      "app_visibility": "public",
      "path": "callables/backup_project/",
      "sha256": "..."
    },
    "fetch_github_issues": {
      "id": "app.fetch_github_issues",
      "version": "1",
      "app_visibility": "private",
      "path": "callables/fetch_github_issues/",
      "sha256": "..."
    }
  },
  "vendored_callables": {
    "local.normalize_issue": {
      "id": "local.normalize_issue",
      "version": "2",
      "path": "vendor/local.normalize_issue/",
      "sha256": "..."
    }
  },
  "frontend": {
    "files": {
      "frontend/index.html": {
        "sha256": "...",
        "content_type": "text/html"
      },
      "frontend/assets/app.js": {
        "sha256": "...",
        "content_type": "text/javascript"
      }
    }
  },
  "storage": {
    "collections": {
      "settings": {
        "description": "Repository and app settings",
        "document_schema_version": 1,
        "document_schema": {
          "type": "object",
          "properties": {
            "repository": { "type": "string" }
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
            "status": { "type": "string" }
          },
          "required": ["title"],
          "additionalProperties": true
        }
      },
      "metadata": {
        "description": "Backup timestamps and sync metadata",
        "document_schema_version": 1
      }
    }
  },
  "declared_effects_summary": [
    "read and write app-local storage",
    "create app/runtime-managed files",
    "make read requests to approved public web hosts",
    "make read and write requests through connected HTTP/API integrations",
    "upload files through connected Drive integrations"
  ],
  "package_review": {
    "approved_extra_packages": [
      {
        "runtime": "python",
        "package": "pypdf==4.3.1",
        "used_by": ["app.backup_project@1"]
      }
    ]
  },
  "hashes": {
    "algorithm": "sha256",
    "manifest_without_hashes": "...",
    "bundle": "..."
  }
}
```

`requires.omnideck_core` is a coarse runtime-family check. Callable resolution
uses exact ids in `core_dependencies`.

`integration_uses` is the canonical saved-manifest field for connected-service
requirements. It is derived from registered callable dependencies on integration
catalog callables, not hand-authored by the agent. Each key is an app-level
alias such as `github` or `drive_backup`. The saved bundle records the
integration facade ref, provider/kind/access requirements, backing core
callable, and user-facing purpose so a saved/imported app can be reviewed and
mapped to local connected accounts.

`web_allowlist` is the canonical app manifest field for public, unauthenticated
web hosts. App callables may pass URLs on these hosts to
`omnideck.http.fetch@1`, and app frames may load images/media from these hosts
when CSP is generated. The allowlist is user-reviewed on save/import. It is not
an integration use and it carries no credentials.

`declared_effects_summary` is author-visible documentation, not review ground
truth. The save/import review derives enforceable effects from `core_dependencies`
and the effect metadata declared by those exact core callable versions, including
transitive dependencies from app and vendored callable manifests.

## Integration Use Resolution

Integration uses are immutable app-version metadata. The mapping from a derived
app alias to a user's connected integration is install/runtime state, not part
of the exported immutable code bundle:

```json
{
  "app_id": "app_project_backlog",
  "integration_account_mappings": {
    "github": {
      "connected_integration_id": "github_api",
      "approved_at": "2026-07-05T20:05:00Z"
    },
    "drive_backup": {
      "connected_integration_id": "google_workspace",
      "approved_at": "2026-07-05T20:06:00Z"
    }
  }
}
```

Resolution rules:

1. Save/import review shows every `integration_uses` entry derived from callable
   dependencies.
2. If no connected integration satisfies an alias, the app can be saved or
   imported but that alias is `unconfigured` until the user connects one.
3. If exactly one connected integration satisfies provider/access constraints,
   Omnideck may suggest it but still records the user's approval.
4. If multiple integrations satisfy the alias, the user chooses one.
5. Imported apps never carry another user's resolved integration ids. Import
   starts with `integration_uses` only and requires local user selection.
6. Runtime integration facade calls receive the app alias and app context.
   Omnideck resolves alias plus app id to a connected integration server-side,
   then invokes the backing core callable.
7. If the alias is missing, unconfigured, disabled, or lacks access, the core
   callable returns `INTEGRATION_NOT_CONNECTED` or
   `INTEGRATION_PERMISSION_DENIED`.

## Frontend Files

The frontend bundle is static files under `frontend/`. For v1:

- `frontend/index.html` is required,
- all referenced files must live under `frontend/`,
- no file may escape the bundle through symlinks or path traversal,
- runtime serving treats the saved version as read-only,
- frontend files are covered by manifest hashes.

Frontend build tooling is out of scope for this doc. Agent tooling may write raw
HTML/CSS/JS, run a build step into `frontend/`, or copy generated assets there.
The saved version stores the built/servable output.

## App Callable Packages

App callables use the callable package format from
[callable-runtime.md](callable-runtime.md). Inside a saved app version:

```text
callables/{route_name}/
  manifest.json
  requirements.lock
  implementation.py
```

The app version manifest maps public route names to callable packages. The app
router uses that manifest to enforce `app_visibility`.

App callable manifests must include explicit input and output schemas. App
callables never have `agent_binding`.

Saved app callable packages must use exact package dependencies. If a callable
declares package dependencies, its package includes the ecosystem-specific lock
file generated at save time, such as `requirements.lock` for Python. Save/import
validation fails if a saved callable contains loose dependency ranges or is
missing its required lock.

## Vendored Local Callables

Draft apps may reference live local callables while the agent iterates. Saved
versions copy the selected local callable version into `vendor/`.

Vendoring records:

- original local callable id,
- selected local callable version,
- vendored path,
- hash of the vendored package,
- exact package dependency lock files when the vendored callable declares
  package dependencies,
- transitive callable dependencies needed by the vendored callable.

A saved app never calls back into the live local callable store. Updating a
local callable later does not silently change saved app behavior.

## Core Dependencies

Core callables are not vendored. They are retained runtime APIs owned by
Omnideck. App manifests list exact core callable ids:

```json
{
  "core_dependencies": [
    "omnideck.http.request@1",
    "omnideck.drive.upload_file@1"
  ]
}
```

Do not use open ranges for core callable dependencies. If a newer core callable
version is needed, the agent updates the app and saves a new app version.
Existing saved versions keep their old core dependency list for rollback.

Import validation fails clearly if the target install does not provide an exact
core callable id listed in the manifest.

## Hash Coverage

Hashes provide tamper evidence and exact rollback. They do not mean the code is
trusted.

Hash these inputs:

- every frontend file,
- every app callable package file,
- every vendored callable package file,
- each nested callable manifest,
- each nested dependency lock file,
- app version manifest content excluding computed hash fields,
- normalized bundle inventory.

Do not hash:

- app runtime data under `data/`,
- callable run logs,
- runtime environments,
- integration credentials,
- active version pointers.

Use deterministic path order and normalized JSON serialization for manifest
hashes.

## Import And Export Archive

Exported app archive layout:

```text
app_project_backlog-v3.omnideck-app.zip
  manifest.json
  frontend/
  callables/
  vendor/
  README.json
```

The archive contains the saved app version only:

- frontend files,
- app callable packages,
- vendored local callable packages,
- app version manifest,
- optional human-readable summary metadata.

The archive does not contain:

- integration credentials,
- broker state,
- app runtime data by default,
- callable logs,
- runtime environments,
- local callable store entries outside the vendored copies.

Import steps:

1. Read and validate archive shape.
2. Validate manifest schema.
3. Validate paths are relative and stay inside the archive root.
4. Validate file hashes and bundle hash.
5. Check exact core dependencies exist.
6. Derive effects from exact core callable dependencies.
7. Present review summary, including extra packages, to the user.
8. Require approval for imported extra packages before preparing environments.
9. Prepare package environments in the isolated environment builder.
10. Create a new app id or attach as a new version according to user choice.
11. Copy files into app-owned storage.
12. Set active version only after the import fully succeeds.

Import should never execute app code during validation. Package environment
preparation does execute third-party package install/build hooks, so it happens
only after package review approval and only in the isolated non-root,
no-credential environment builder described by the callable runtime.

## App Data Export

App code/version export is separate from app data backup.

By default, exported app archives do not include `data/`. App-local storage may
contain private user data, sync metadata, repository settings, or generated
state. Including it changes the privacy semantics of sharing an app.

If a user wants a full backup, use a separate app data export path:

```text
export app definition only
export app data backup
export support/debug bundle
```

For the backlog manager, app data backup should use
`omnideck.app.storage.export@1` and optionally `omnideck.drive.upload_file@1`.
That is user data backup, not app sharing.

## Rollback

Rollback changes the app's active version pointer to an existing saved version:

```json
{
  "active_version": "2"
}
```

Rollback must not mutate saved version files. It should:

- verify the target version exists,
- verify required core dependencies are available,
- update the active version pointer atomically,
- record a management event,
- leave app data untouched unless a future migration system says otherwise.

App data is scoped to the app installation, not the app version. Rolling back
from v3 to v2 reuses the same app storage. If app data migrations are later
introduced, rollback needs a migration/compatibility policy before destructive
schema changes are allowed.

V1 compatibility stance: app storage is shared across versions, so app-authored
documents should be version-tagged and read tolerantly. Older app code must
ignore unknown fields and handle missing optional fields. Newer versions must
avoid destructive rewrites that make old saved versions unable to read core
records unless a future migration system explicitly declares rollback
compatibility. Save review should flag storage schema changes as a compatibility
risk, not silently treat them as implementation detail.

## Compatibility Checks

When saving, importing, or activating an app version, validate:

- manifest schema version is supported,
- exact core callable dependencies exist and are not disabled,
- app callable manifests are valid,
- app callable package dependencies are exact and lock files are present when
  required,
- input/output schemas are valid,
- `app_visibility` is valid for every route,
- vendored callable dependencies resolve inside the bundle or to core callables,
- frontend entrypoint exists,
- `integration_uses` entries have valid aliases, integration facade refs,
  provider/kind/access values, backing core callables, and any local connected
  account mapping satisfies the derived use,
- `web_allowlist` entries are valid exact hostnames with no wildcards or IP
  literals, and every host is shown in save/import review,
- hashes match,
- storage review metadata is well-formed,
- storage document schemas are well-formed and schema deltas are flagged for
  save/import review.

If a retained core callable version is disabled for security reasons, activation
fails with `CORE_CALLABLE_DISABLED` and remediation guidance.

## Review Summary

The app manifest should be sufficient to generate a user-facing review summary,
but the effect list is derived from exact core callable dependencies, not from
author-written summary text:

```text
This app contains:
- frontend files
- 3 app actions
- 1 vendored reusable automation

This app may:
- read and write app-local storage
- create app/runtime-managed files
- make read requests to approved public web hosts
- make read and write requests through connected HTTP/API integrations
- upload files through connected Drive integrations

This app may load or fetch public web data from:
- status.example.com -- Read the public service status feed

This app uses connected accounts:
- GitHub account for github -- Read and close issues for the backlog app
- Google Drive account for drive_backup -- Upload backup files

This app wants to install code packages:
- pypdf==4.3.1

This app stores local data:
- repository and app settings
- local backlog items
- backup and sync metadata
```

This summary is not a permission grant. Integration access is still enforced by
the supervisor and broker.

## Open Decisions

- Whether draft apps need multiple named drafts or just one mutable draft per
  app.
- Whether imported archives can attach as a new version of an existing app or
  always create a new app id in v1.
- Exact app id generation and collision behavior on import.
- Whether hash coverage should include a Merkle-style file tree in addition to
  per-file hashes.
- Whether app data migrations are a v1 requirement or deferred until a concrete
  app needs schema evolution.
- Exact archive extension and MIME type.
