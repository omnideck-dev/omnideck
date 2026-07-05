# App Builder UX

> User-facing experience for creating, editing, reviewing, running, importing,
> debugging, and managing AI workbench apps with the agent.

## Relationship To Other Designs

[agent-build-tooling.md](agent-build-tooling.md) defines the agent/backend tools.
[frontend-runtime.md](frontend-runtime.md) defines app frame containment.
[bundle-format.md](bundle-format.md) defines saved versions and import/export.
[app-router.md](app-router.md) defines invocation results and errors.
[feature-flags.md](feature-flags.md) defines rollout gates and disabled
behavior.

This document owns the human workflow and UI surfaces. It intentionally avoids
implementation details unless they affect what the user sees.

The UI must respect the `ai_workbench.*` feature flags. When the feature is off,
the collapsible Apps section, builder entry points, app import/export controls,
and "debug with agent" app affordances should be hidden or disabled. If a user
reaches a gated route through a stale link, show a plain unavailable state rather
than an app frame. Disabling the feature should not imply app data deletion.

## Goals

- Let users build apps by describing what they want to the agent.
- Keep the first screen useful: chat plus live draft preview, not a marketing or
  documentation page.
- Let users run saved apps as durable workspaces.
- Make app effects, package installs, integration use, and imported-code risk
  reviewable without exposing internal callable jargon.
- Make failures actionable through "debug with agent".
- Keep app management simple: open, edit, disable, roll back, export, import,
  delete, and inspect storage.
- Show the user exactly what the app is made of: its actions and the source of
  each, both while building and in the saved app. Nothing about the app is
  hidden from the user who owns it.
- Make building collaborative: the user tests the live app while the agent
  watches the same run log and reacts to what the user just did.

## User Language

Avoid exposing "callable" in primary UI. Suggested product language:

| Internal term | User-facing language |
|---|---|
| App callable | App action |
| Public app callable | Button/action the app can run |
| Private app callable | Helper action |
| Local callable | Reusable automation |
| Core callable | Omnideck capability |
| App version | Saved version |
| Draft app | Draft |
| Effects | What this app may do |
| Package dependencies | Code packages |

Advanced/debug views can show exact internal ids when needed.

## Primary Build Flow

```text
User asks for an app
  -> agent proposes app shape
  -> agent creates draft
  -> shell opens builder with chat + preview
  -> agent edits frontend and app actions while preview refreshes
  -> user watches and tests in preview
  -> external effects dry-run until user approves real preview calls
  -> user reviews effects/packages/integrations
  -> user saves version
  -> app appears in app library
```

The builder should feel like a workspace. The user should not need to understand
where frontend files, app actions, package locks, and bundle manifests live.

## Agent And User Authority

Users build apps by talking to the core chat agent. The agent can create and
edit drafts, write frontend/action files, run preview actions, inspect
sanitized run logs, and explain review results. The agent should not directly
save a version, roll back the active version, export an app bundle, or create a
support bundle.

Those actions belong to trusted Omnideck UI controls because they commit code,
change which version is active, or export shareable data. The agent can prepare
the draft, explain the risk, and guide the user to the action, but the user
must explicitly click the trusted control.

## Builder Layout

Recommended v1 layout:

```text
---------------------------------------------------------
Omnideck shell chrome: app title, draft/saved status, save
---------------------------------------------------------
Left:   agent chat and task history
Center: live app preview in the sandboxed frame
Right:  app structure — actions and their source, effects,
        packages, local data
Bottom or side drawer: shared run log, review, errors when needed
---------------------------------------------------------
```

The preview is the actual app frame running through the same containment model
as saved apps. It should not be a screenshot or fake renderer.

Builder chrome should include:

- app title,
- draft or saved status,
- active saved version if editing from one,
- save/version action,
- review summary access,
- debug/log drawer access,
- app menu for export, import, rollback, disable, delete.

## Transparency

The user owns the app and can see everything in it. The builder's right-hand
structure panel lists every app action, public and helper, and lets the user
open the source of any of them. It also shows what the app may do (derived
effects), the packages it installs, and the local data it keeps. The same
inspection is available from a saved app, not only while building.

Integrations appear as actions the app's code calls, not as a separate
permission surface. Opening an action's source shows which Omnideck
capabilities and integration callables it uses. The app never receives
credentials; the broker still decides whether each operation is allowed.

## Agent Collaboration States

The builder should show the agent's current mode in plain language:

| State | User meaning |
|---|---|
| Planning | The agent is deciding app structure |
| Editing | The agent is changing the draft |
| Preview broken | The draft is visible but currently has build, schema, UI, or runtime errors |
| Testing | The agent is running preview actions |
| Waiting for approval | The user must approve packages, real external preview effects, or save |
| Blocked | The agent needs a user decision or external integration |
| Saved | The draft became an immutable saved version |

Do not stream internal file paths or stack traces into the main user flow. Put
technical detail behind an expandable debug view.

## Draft Preview

Preview should:

- run in the sandboxed app frame,
- remain visible while the agent builds, even when the draft is incomplete or
  temporarily broken,
- call draft app actions through preview routes,
- default external-effect actions to dry-run mode,
- clearly show it is a draft,
- preserve enough state for iteration,
- expose failed action `call_id` to the shell,
- surface runs the user triggers in the preview to the agent through a shared
  run log, so the agent can react to what the user just tested,
- let the user ask the agent to debug a failure.

Preview should not:

- hide that a draft is currently broken,
- call real third-party APIs or perform external writes before user approval,
- relax iframe/CSP restrictions,
- call arbitrary Omnideck APIs,
- use saved app routes for draft callables,
- make save implicit.

Dry-run preview should show what would happen without doing it:

```text
This action would:
- read GitHub issues through the github integration
- create a backup file
- upload the backup to Drive

[Allow real preview call] [Keep dry-run]
```

When the user allows a real preview call, scope approval to the current draft,
action, and preview session. If the agent changes the draft's external effects,
ask again.

## Save Review

Saving a draft creates a saved version. Before save, show a review summary:

```text
This app contains:
- frontend files
- 4 app actions
- 1 reusable automation copied into the app

This app may:
- read and write app-local storage
- make HTTP/API requests through connected integrations
- upload backup files to Drive

This app wants to install code packages:
- pypdf==4.3.1

This app stores local data:
- repository settings
- local backlog items
- backup metadata
```

Review rules:

- Explain effects as behavior, not permissions.
- Make clear existing broker/integration grants still decide whether operations
  are allowed.
- Separate package approval from integration/effect review.
- Show changed effects when saving an update from an existing app.
- Let the user cancel save and keep editing the draft.

## Running Saved Apps

Saved apps open as durable workspaces from the app library. The saved app run
view should show:

- trusted Omnideck shell chrome,
- app title and saved version,
- imported/draft status when relevant,
- review/effects summary access,
- edit with agent,
- disable/export/delete menu,
- debug with agent when an action fails.

The app frame should not be able to hide trusted shell chrome or impersonate
Omnideck controls.

## Editing Existing Apps

Editing a saved app creates a draft from the active version:

```text
Open saved app
  -> Edit with agent
  -> clone active version into draft
  -> agent applies requested change
  -> preview/test
  -> review delta
  -> user saves new version through trusted UI
```

The user-facing review should emphasize deltas:

- new or removed app actions,
- changed external effects,
- changed package approvals,
- changed local data shape,
- changed integration expectations,
- frontend changes.

The old version remains available for rollback.

## Debug With Agent

When an app action fails, the shell should show:

```text
Something went wrong.
[Try again] [Debug with agent] [Details]
```

`Details` can show a short structured error and `call_id`. `Debug with agent`
hands the app id, version or draft id, route name, and `call_id` to the agent.

The user experience should be:

```text
User clicks Debug with agent
  -> agent reads sanitized run log
  -> agent explains likely cause
  -> if editable, agent proposes or applies a draft fix
  -> user tests again
```

Examples:

- missing integration connection,
- broker permission denied,
- package install failed,
- app action returned invalid data,
- upstream API rate limit,
- runner timeout or resource limit.

## App Library

The app library lists durable apps, not one-off artifacts.

Recommended list columns:

- app name,
- status: active, disabled, draft, imported,
- active version,
- last opened,
- recent failure indicator,
- storage size,
- integration/effect summary.

Primary actions:

- open,
- edit with agent,
- create new app,
- import app.

Secondary actions:

- export,
- rollback,
- duplicate,
- disable,
- delete,
- manage data,
- create support bundle.

## Import Review

Imported apps contain code. Treat import as explicit risk acceptance.

Import flow:

```text
Choose app archive
  -> verify archive and hashes
  -> check core callable compatibility
  -> show app contents/effects/packages/storage
  -> show missing integrations, if known
  -> user enables or keeps disabled for inspection
```

Review copy should say:

```text
This app contains code.
Only import apps from sources you trust.
```

Imported apps should default to disabled until review completes. The agent can
help inspect and explain an app, but it must not auto-enable imported code.

## Rollback

Rollback is a version switch:

```text
Version 4 active
  -> choose rollback to version 3
  -> show review of version 3 effects/packages
  -> make version 3 active
```

Do not mutate version 4. Do not delete app data automatically. If data schema
migrations are added later, rollback must explain whether data is compatible.

## Delete And Disable

Disable stops the app from running without deleting saved versions or app data.
Delete removes the app after explicit confirmation.

Deletion should show:

- saved versions that will be removed,
- app-local data that will be removed,
- package approvals that will be forgotten,
- whether exported artifacts or Drive uploads remain outside Omnideck.

For v1, prefer disable as the low-risk action and keep delete explicit.

## Operations In UX

The product should support users without requiring maintainers to inspect raw
container files.

UX surfaces needed:

- recent failures in app library,
- app diagnostics drawer,
- create support bundle,
- storage usage per app,
- package approvals per app,
- version history,
- disabled/quarantined warning state,
- "debug with agent" from failures.

Operations detail lives in [operations-support.md](operations-support.md).

## Mockup Inventory

Static HTML mockups live in `plans/ai-workbench/mockups/`. `index.html` is a
single self-contained viewer: a left nav switches between the screens, so the
whole flow can be walked without opening files individually.

```text
plans/ai-workbench/mockups/index.html
  01  App library
  02  Build with agent   (chat + live preview + app-structure/source panel)
  03  Action source      (an action's metadata and its source)
  04  Save review
  05  Run a saved app
  06  Debug with agent
  07  Import an app
```

Mockups use the real first-screen experience: builder, app shell, or review
flow. There is no landing page.

## Open Decisions

- Final feature name in product UI.
- Whether users see reusable automations as a library in v1.
- Whether app builder chat and preview are split pane, tabbed, or drawer-based
  on small screens.
- Exact copy for package approval and imported-code warning.
- Whether save review is mandatory for every version or only when effects,
  packages, or imported code changed.
- Whether app library appears in the main navigation or under an existing
  workbench area.
