# Feature Flags

> Release gating for the AI workbench app/custom-design feature. The feature
> should be safe to merge before it is safe to expose broadly.

## Goals

- Keep the app builder, app runtime, import/export, and public fetch surfaces
  dark by default until the implementation reaches the required security floor.
- Allow developer and private-beta rollout without changing saved app data.
- Make disabling the feature stop new execution immediately while preserving
  drafts, saved versions, app data, logs, and support state for later recovery.
- Ensure the gate is enforced server-side, not only by hiding frontend controls.

## Flag Set

Use one master flag and a small number of narrower rollout flags:

| Flag | Default | Gates |
|---|---|---|
| `ai_workbench.enabled` | off | All AI workbench app surfaces |
| `ai_workbench.builder_enabled` | off | Draft creation/editing, builder UI, agent build tools, draft preview |
| `ai_workbench.runtime_enabled` | off | Saved app frame serving, app invoke routes, app runner launch |
| `ai_workbench.import_export_enabled` | off | Import, export, imported-app enablement |
| `ai_workbench.public_fetch_enabled` | off | `omnideck.http.fetch@1` and `web_allowlist` CSP expansion |

The master flag must be on before any narrower flag takes effect. Production
defaults should keep all flags off until the release owner enables them for a
specific environment, account, or cohort.

## Enforcement Points

Every external entry point checks the relevant flag before doing work:

- App library and builder UI hide or disable the Apps surfaces when disabled.
- Agent app-building tools return `FEATURE_DISABLED` when builder access is
  disabled.
- `POST /api/apps/{app_id}/frames`, draft frame serving, saved frame serving,
  app invoke, call polling, and cancellation routes return `FEATURE_DISABLED`
  when runtime access is disabled.
- The callable runtime refuses to launch app runners when runtime access is
  disabled, even if a route forgot to check.
- User-only save/version activation is blocked when builder access is disabled.
- Import/export routes are blocked when import/export access is disabled.
- `omnideck.http.fetch@1` rejects calls when public fetch is disabled, and frame
  CSP generation omits `web_allowlist` host expansion.

Flag checks should happen before loading untrusted app code, preparing package
environments, invoking broker-backed core callables, or starting runner
processes.

## Disabled Behavior

When a flag is disabled:

- existing drafts, saved app versions, app-local data, logs, and package
  metadata remain on disk,
- no new preview sessions, app frames, app invocations, saves, imports, exports,
  or app runner launches start for the gated surface,
- active preview sessions are invalidated,
- in-flight app runner call trees receive cancellation and cannot launch new
  child callables,
- support and diagnostics can still read existing logs if operations chooses to
  expose them, but they must not execute app code.

Disabling the flag is a runtime stop, not data deletion. Re-enabling should make
previous drafts and saved app versions visible again subject to normal
compatibility checks.

## Error Shape

Use a stable error code wherever a gated entry point is called while disabled:

```json
{
  "ok": false,
  "error": {
    "code": "FEATURE_DISABLED",
    "message": "AI workbench apps are not enabled for this install.",
    "retryable": false
  }
}
```

Agent tools, app router responses, user-only management routes, and core
callables should use the same code with surface-specific safe messages.

## Rollout Stages

Recommended rollout:

1. Developer only: `ai_workbench.enabled` plus builder/runtime flags on for local
   development installs.
2. Internal beta: enable builder/runtime for trusted accounts; keep
   import/export and public fetch off unless explicitly testing them.
3. Private beta: enable builder/runtime for selected users; enable
   import/export only after import review and support paths are ready.
4. Wider release: enable all intended v1 flags after the security checklist,
   browser compatibility tests, support flows, and quota behavior pass.

## Tests

Feature-flag tests should cover:

- Apps nav and builder UI hidden/disabled when flags are off.
- Agent build tools return `FEATURE_DISABLED`.
- Frame creation and invoke routes return `FEATURE_DISABLED`.
- Runtime launcher refuses app runner execution even when called directly.
- Disabling runtime invalidates preview sessions and cancels active app call
  trees.
- Re-enabling does not mutate saved app versions or app-local data.
- Public fetch disabled blocks `omnideck.http.fetch@1` and omits
  `web_allowlist` from CSP.
