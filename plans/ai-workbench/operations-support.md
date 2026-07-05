# Operations And Support

> Runtime operations, user support, diagnostics, quotas, retention, and recovery
> behavior for AI workbench apps.

## Goals

- Help users and maintainers understand app failures without raw container
  access.
- Keep app data, logs, package environments, and scratch from consuming disk
  indefinitely.
- Provide safe recovery actions: retry, debug, disable, roll back, export data,
  and create support bundle.
- Make upgrades and disabled core callable versions understandable.

## Runtime State To Manage

| State | Owner | Notes |
|---|---|---|
| Feature flags | Omnideck runtime | Gate builder, runtime, import/export, and public fetch surfaces |
| Draft apps | App builder | Mutable, can be abandoned or saved |
| Saved app versions | App runtime | Immutable, rollback target |
| App-local storage | Core storage callable | Durable user data |
| Runner scratch | Callable runtime | Per invocation, temporary |
| Package environments | Environment builder | Reused by dependency hash |
| Callable run logs | Callable runtime | Bounded diagnostics |
| Support bundles | User requested | Explicit export, redacted |
| Imported app archives | App manager | May be disabled/quarantined |

## User-Facing Support Actions

Minimum actions:

- retry failed app action,
- debug with agent,
- view technical details with `call_id`,
- disable app,
- roll back to prior version,
- export app bundle,
- export app data,
- create support bundle,
- clear old logs/cache,
- delete app and app data.

Each action should clearly state whether it affects:

- saved app versions,
- app-local data,
- external files uploaded to integrations,
- exported artifacts,
- logs/support bundles,
- package environments.

## Diagnostics

Every failed app action should have:

```text
short user message
structured error code
call_id
app_id
app_version or draft_id
public route name
timestamp
```

The diagnostics drawer can show:

- recent runs,
- failure count by action,
- last package install failure,
- storage size,
- active version,
- pending package approvals,
- missing integration status,
- disabled/quarantined state.

The agent-facing diagnostic tools can expose more detail, but still sanitized.

## Support Bundles

Support bundle export must be explicit. Suggested scopes:

- one `call_id`,
- one app over a date range,
- one failed save/import attempt,
- one package environment preparation attempt.

Support bundle contents:

```text
metadata.json
app_manifest.json
run_events.jsonl
stdout_excerpt.log
stderr_excerpt.log
package_install.log
environment_metadata.json
redaction_report.json
```

Do not include by default:

- integration tokens,
- cookies,
- broker vault data,
- raw host paths,
- full app storage data,
- full request/response bodies from upstream APIs.
- full stdout/stderr or package install logs unless the user explicitly expands
  the bundle scope after review.

Support bundles should include a `redaction_report.json` that explains what
classes of values were redacted. Redaction is not a security boundary.

Logs are a likely exfiltration channel for malicious app code and package build
hooks. Default support bundles should include bounded excerpts, structured
events, sizes, hashes, and redaction reports rather than raw full logs. Full log
inclusion requires a second explicit user confirmation that explains the risk.

## Retention And Pruning

Use independent quotas for:

- callable run logs,
- runner scratch,
- package environments,
- draft apps,
- support bundles,
- app-local storage.

Recommended v1 behavior:

- runner scratch is deleted after invocation finishes, unless pinned for active
  debugging,
- successful run logs have shorter retention than failed run logs,
- failed run logs can be pinned while the user is debugging,
- package environments are evicted by least-recently-used dependency hash,
- abandoned drafts expire after a configurable age,
- support bundles are user-visible files and are not silently deleted unless the
  product has a general downloads cleanup policy,
- app-local storage is durable until the user deletes app data.

When quota is exceeded, prefer:

1. remove stale scratch,
2. remove unpinned successful run logs,
3. remove old failed run logs,
4. evict unused package environments,
5. warn user before deleting drafts or app data.

## Disable, Quarantine, And Recovery

States:

| State | Meaning |
|---|---|
| Feature disabled | The AI workbench surface is hidden or blocked by release flag |
| Active | App can run |
| Disabled | User/admin stopped app from running |
| Quarantined | Runtime blocked app for security or compatibility reason |
| Import pending | Imported app not accepted yet |
| Broken | App cannot run until dependencies/integrations are repaired |

Feature-disabled is not an app data state. It is a release gate. When a flag is
off, Omnideck should preserve drafts, saved versions, app-local storage, logs,
and package metadata, but block new previews, invocations, saves, imports,
exports, and runner launches for the gated surface. Diagnostics may still show
existing failures if operations exposes them, but support actions must not run
app code while the runtime flag is off.

Quarantine triggers:

- disabled required core callable version,
- failed import hash verification,
- known vulnerable package approval,
- incompatible manifest schema,
- repeated runner sandbox violation,
- app references unavailable runtime capabilities.

Recovery should offer:

- debug with agent,
- migrate app to newer core callable version,
- roll back,
- disable permanently,
- export app data,
- create support bundle.

## Upgrade Behavior

On Omnideck upgrade:

- verify retained core callable ids still register,
- mark disabled core versions explicitly,
- scan saved apps for compatibility,
- do not rewrite saved app versions in place,
- surface apps needing migration,
- let agent create a new draft/version for migration.

Upgrade checks should not require running imported or saved app code.

## App Data Operations

App data should be manageable separately from app versions.

User operations:

- view storage summary,
- export app data,
- delete app data,
- include/exclude app data in backup,
- restore app data from backup if supported later.

Deleting an app should not silently delete external Drive uploads or future
promoted artifacts. Those are outputs the user received outside the app.

## Metrics And Local Health

If local metrics are added, keep them product-support oriented:

- action success/failure counts,
- average duration,
- timeout count,
- package install failure count,
- disk usage by category,
- feature-flag disabled counts by blocked surface,
- disabled/quarantined app count.

Do not add external telemetry without a separate privacy design.

## Open Decisions

- Default retention durations and disk quotas.
- Whether support bundles are stored in app data, downloads, or artifact system.
- Whether users can pin logs manually.
- Whether app data export is JSON-only for v1.
- Exact quarantine triggers and user copy.
- Whether local health metrics appear in app library or only diagnostics.
