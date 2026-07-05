# Project Backlog Manager Use Case

> Reference scenario for stress-testing AI workbench designs. This is not an
> implementation plan; use it to check whether proposed callable, app, storage,
> integration, debugging, and packaging designs hold together.

## Scenario

A user owns an open source app and wants Omnideck to build a project management
app for it.

They ask the agent to create an app that helps them manage project work across:

- GitHub issues for the public repository,
- backlog items they create locally in Omnideck,
- project backups stored in their connected Drive integration.

The user is not expected to write code or understand callable/package internals.
They describe the desired workflow, and the agent builds the app, backend logic,
and any reusable automations needed.

## User Goals

The app should let the user:

- View GitHub issues for a configured open source repository.
- Create and edit local backlog items that are not GitHub issues.
- See GitHub issues and local backlog items together in one backlog view.
- Prioritize, categorize, and track status for local backlog items.
- Close GitHub issues from the app when work is complete.
- Keep local backlog data private to this Omnideck install/app.
- Back up the project backlog and issue snapshot to their Drive integration.
- Return to the app from the Omnideck UI like a durable workspace, not a one-off
  artifact.
- Ask the agent to modify or debug the app later.

## Integration Expectations

The app should use integrations the user has already connected and granted to
Omnideck.

Expected external capabilities:

- GitHub issue read access through an HTTP/API or GitHub integration.
- GitHub issue write access for closing issues.
- Drive write access for backup export.

This use case should not introduce a second integration permission model. If the
user has not granted the needed integration access, the app should fail clearly
and explain what is missing.

## Local Data Expectations

The app needs local app-owned data for backlog items and settings, including:

- repository configuration,
- local backlog item records,
- local status/priority/category metadata,
- backup timestamps or sync metadata.

The data should belong to the app, not to a random file path the frontend can
mutate directly. A saved/exported app should make clear what local data it stores
and what is included in backups.

## Agent Workflow Expectations

The agent should be able to:

- Discover the core capabilities available for GitHub/API calls, app-local
  storage, file/export creation, and connected integrations.
- Notice when a higher-level capability does not exist yet and create the needed
  app/local callable using lower-level primitives. For example, if there is no
  ready-made "backup project to Drive" callable, the agent can create one that
  prepares the backup payload and invokes the Drive integration.
- Build the frontend experience.
- Build the backend app logic.
- Test the app's main workflows.
- Inspect logs and failures when GitHub, local storage, or Drive operations fail.
- Iterate on app logic when the user asks for changes.
- Save a versioned app bundle that does not silently change when reusable local
  automations change later.

## Failure Cases To Design For

The app should produce useful errors and logs when:

- The GitHub/API integration is missing or lacks write access.
- GitHub returns an HTTP error or rate-limit response.
- A local backlog record is malformed or missing.
- A backup file cannot be created.
- Drive upload fails or the Drive integration is not connected.
- An app callable hangs, crashes, exceeds resource limits, or has missing package
  dependencies.
- The agent needs to debug a failing app action on behalf of the user.

## Design Pressure

This scenario is useful because it exercises:

- Agent-created apps.
- Agent-created backend logic.
- Agent-created callables that wrap lower-level core/integration capabilities.
- Public app actions called by a frontend.
- Private app helper logic.
- App-scoped local storage.
- External API reads and writes.
- Integration-backed writes.
- File/export creation.
- Drive backup.
- Versioned app bundles.
- Import/export review summaries.
- Callable logs and support/debugging workflows.
- Runtime isolation for agent-authored code.
- Clear distinction between existing integration grants and app-level behavior.

## Open Questions This Use Case Should Keep Honest

- Can the app do useful external work without giving app code broad ambient
  access to the host or Omnideck process?
- Can maintainers, users, and the agent understand why a project action failed?
- Can the app be saved, updated, rolled back, exported, and imported without a
  package-manager-style user experience?
- Can local data remain app-scoped while still being easy to back up?
- Can the user-facing UX stay simple even though the implementation involves
  callables, app bundles, integrations, and runtime isolation?
