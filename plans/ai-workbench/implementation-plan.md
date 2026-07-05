# Implementation Plan

> Proposed build order for the AI workbench feature. This turns the design docs
> into phases with acceptance criteria and dependencies.

## Goals

- Build the smallest useful vertical slice before broadening the surface.
- Keep existing integration tools working while core callables are introduced.
- Prove isolation, invocation, storage, routing, and preview before import/export
  polish.
- Make each phase testable.

## Phase 0: Prototype And Repo Prep

Purpose: prove the shape without committing to the final product surface.

Work:

- add the `ai_workbench.*` feature flags with production defaults off,
- settle source tree locations for core callable packages,
- add manifest loading for a tiny core callable catalog,
- prototype parent-managed runner RPC with one Python callable in
  developer-only mode,
- prototype sandboxed iframe plus parent bridge,
- prototype app draft storage layout.

Acceptance:

- app builder/runtime/import routes and tools are dark unless flags are enabled,
- one toy app action can be invoked through the app router shape,
- runner returns structured result/error,
- frontend frame calls parent bridge, not arbitrary `/api/*`,
- prototype notes identify browser and runner incompatibilities.

## Phase 1: Core Callable Catalog

Purpose: create the programmatic callable layer under existing tools.

Work:

- define core callable manifest schema,
- register core callable ids at startup,
- wrap one existing integration tool as a core callable,
- expose callable discovery to agent tooling,
- add effect metadata and structured errors,
- enforce retained `@N` core callable ids.

Acceptance:

- existing agent-facing tool behavior stays unchanged,
- local/app callable code is not needed yet,
- discovery can list core callable schemas and effects,
- tests cover missing/disabled core callable ids.

## Phase 2: Local Callable Runtime

Purpose: let Omnideck run agent-authored backend logic safely enough for v1.

Work:

- implement native runner launcher,
- add `runner_local` and per-app `runner_app_<id>` users plus control socket,
- apply app-specific runner users, no-cap, no-new-privs, resource-limit controls,
- require seccomp network denial and Landlock filesystem confinement for normal
  app execution,
- implement runner RPC protocol,
- implement call graph limits, cancellation, timeouts, and data caps,
- implement local callable store plus create/update/test/delete authoring APIs,
- implement environment builder launcher path, dedicated build user, exact
  dependency locks, trusted fetch, offline hooks, and hash-verified read-only
  package cache,
- persist callable run logs.

Acceptance:

- local callable runs out-of-process as `runner_local`,
- app runners do not share one uid across app installs,
- no credentials or server import paths are present in runner env,
- runner cannot open network sockets,
- Landlock confines runner filesystem access,
- disabled core dumps and reduced syscall surface are verified,
- one app runner cannot read another app runner's scratch or app data path,
- dependency calls route through parent-managed invocation,
- cancellation kills the full call tree,
- oversized results fail with structured errors,
- builder runs as dedicated build user with `NO_NEW_PRIVS`, dropped caps,
  seccomp-denied hook network, Landlock confinement, disabled core dumps, and
  read-only hash-verified package cache for hooks,
- failed runs can be inspected by `call_id`.

## Phase 3: First Core App Capabilities

Purpose: make app/local callables useful without ambient access.

Work:

- implement `omnideck.app.storage.*@1`,
- implement `omnideck.file.read@1` and `omnideck.file.write@1`,
- implement `omnideck.http.request@1`,
- implement `omnideck.drive.upload_file@1`,
- implement integration facade catalog entries, derived integration uses, and
  runtime account mapping resolution,
- add effect summaries and logs for each,
- implement dry-run behavior for external-effect core callables.

Acceptance:

- backlog manager can store local backlog records,
- local callable can create backup file refs through core file callables,
- local callable can make dry-run and live broker-mediated, alias-scoped
  HTTP/API requests,
- core callables reject undeclared or unmapped integration aliases,
- core callables validate all untrusted inputs.
- risky core callables are reviewed for worker-process isolation.

## Phase 4: App Bundles And Router

Purpose: make durable app versions with invokable app actions.

Work:

- implement draft app storage,
- implement saved app version layout,
- implement bundle manifest schema and hash coverage,
- persist derived `integration_uses` in saved bundle manifests,
- implement local-callable vendoring into saved app versions,
- implement public/private app callable resolution,
- implement app invoke route,
- implement app context injection,
- implement structured response/error envelopes,
- implement active-version resolution and rollback.

Acceptance:

- saved app version runs without referencing live local callable store,
- app router invokes only public app actions,
- private helper app callables are callable only from declared dependencies,
- app context injection is applied for app callables and app-scoped core
  callables,
- saved app can resolve derived integration aliases to user-selected connected
  accounts,
- rollback switches active version without mutating versions,
- app invoke errors expose `call_id`.

## Phase 5: Frontend Runtime And Builder Preview

Purpose: let users see and test apps while preserving browser containment.

Work:

- serve app frontend files from saved/draft storage,
- create sandboxed opaque-origin iframe host,
- implement parent bridge and tiny SDK,
- implement `POST /api/apps/{app_id}/frames` and draft frame token minting,
- validate frame tokens server-side for saved and draft invoke routes,
- enforce CSP,
- harden XSRF including `PATCH`,
- implement draft preview route,
- implement dry-run preview invocation and live-effect approval checks,
- test latest Chrome/Edge, Firefox, and Safari.

Acceptance:

- disabled runtime flags prevent frame token minting, frame serving, app invoke,
  and app runner launch,
- app frame cannot directly call arbitrary Omnideck APIs,
- app frame invokes actions only through parent bridge,
- cross-app frame token binding rejects invoking another app's actions,
- browser compatibility traps are tested,
- preview uses same containment model as saved app run,
- shell owns trusted app chrome.

## Phase 6: Agent Build Tooling

Purpose: let the agent build, test, and debug app drafts end to end.

Work:

- implement the seven-tool app build surface:
  `edit_app`, `app_callable_catalog`, `app_add_callable`,
  `app_set_frontend`, `app_configure`, `app_test`, and `app_get_run`,
- route program-file edits through the agent's existing file tools instead of
  app-specific file APIs,
- implement callable, package, local callable, and integration facade discovery
  through `app_callable_catalog`,
- implement schema-from-code registration for app callables,
- implement shared run inspection through `app_get_run`,
- implement package approval handoff,
- add or update an agent skill for building apps.

Acceptance:

- disabled builder flags hide or disable agent app-building tools and return
  `FEATURE_DISABLED` if called directly,
- agent can build the backlog manager draft from user request,
- agent can test storage and dry-run HTTP/Drive actions,
- agent can request user approval for selected live preview effects,
- agent can repair a failed app action from `call_id`,
- save review blocks pending extra packages,
- saved app version is reproducible from bundle metadata.

## Phase 7: UX And App Management

Purpose: make the feature usable and supportable.

Work:

- implement app library,
- implement builder shell with chat plus preview,
- implement save review,
- implement user-only save/version activation action,
- implement import review,
- implement app run shell,
- implement version history and rollback UI,
- implement app bundle export UI,
- implement disable/delete/manage data flows,
- implement support bundle creation.

Acceptance:

- Apps navigation, builder shell, run shell, import/export, and management
  controls respect the `ai_workbench.*` flags,
- user can create, save, reopen, edit, and roll back an app,
- save/export/rollback/support-bundle actions require explicit user action and
  are not agent tools,
- imported app requires explicit review,
- failed actions offer debug with agent,
- app library shows status, version, failures, and storage size,
- support bundle export requires explicit user action.

## Phase 8: Import, Export, And Hardening

Purpose: make apps portable and safer to operate.

Work:

- implement archive import/export,
- implement compatibility checks,
- implement hash verification,
- implement disabled/quarantined states,
- add redaction tests for logs/support bundles,
- add resource quota/pruning behavior,
- broaden core callable test coverage.

Acceptance:

- exported app imports into a compatible install,
- missing core callable versions fail clearly,
- vulnerable disabled core callable versions fail safely,
- support bundles redact known secret shapes,
- quotas prevent app/log/package data from consuming disk unchecked.

## Cross-Phase Test Strategy

Add tests at the boundary where trust changes:

- manifest validation before loading code,
- runner launch and sandbox controls,
- parent-managed dependency invocation,
- core callable input validation,
- broker permission denial propagation,
- app router public/private checks,
- frontend bridge source validation,
- CSP and iframe behavior in browser tests,
- import/export hash compatibility,
- save review and package approval blocking.
- feature-flag off behavior at every entry point, including direct API/tool
  calls and runtime launcher calls.

## First Vertical Slice

The smallest useful slice is:

```text
one app draft
one static frontend
one public app callable
app storage get/set
app invoke route
sandboxed preview
save version
run saved app
debug failed call by call_id
```

Drive upload, HTTP request, import/export, and full app library can follow after
that slice proves the architecture.

## Open Decisions

- Whether import/export ships before or after the first private beta.
- Whether any developer-only unsafe execution mode exists when seccomp/Landlock
  are unavailable.
- Exact browser automation suite for iframe/CSP compatibility.
- Whether support bundle export is phase 7 or phase 8.
