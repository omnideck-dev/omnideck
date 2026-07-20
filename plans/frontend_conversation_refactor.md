# Frontend Conversation and Desktop Refactor

## Purpose and lifecycle

This document tracks the incremental frontend refactor that began with
[#196](https://github.com/omnideck-dev/omnideck/pull/196). The work separates
conversation transport, event interpretation, derived UI models, navigation,
and desktop layout without requiring a router or a backend protocol split.

Keep this file updated as each stage lands. Delete it in the final PR after all
completion criteria in this document are satisfied. The deletion is part of
the refactor's definition of done, not a later documentation chore.

## Working convention

Use one long-lived workspace for the remaining stages:

- worktree: `/home/larry/repos/omnideck.worktrees/frontend-refactor`;
- branch: `refactor/frontend-architecture`.

Before beginning a stage, fetch `origin/main` and rebase this branch onto it.
After a stage PR merges, fetch and rebase again before starting the next stage.
This keeps the work based on the latest merged architecture and prevents
squash-merged commits from reappearing in later PR diffs. Keep each stage as a
separate, reviewable commit or commit series even though the workspace is
reused.

## Why this refactor exists

`DesktopApp` and `useStreamingChat` currently coordinate too many concerns:

- desktop layout and surface selection;
- active-conversation identity and commands;
- the `/api/chat` streaming transport;
- JSONL decoding and live event normalization;
- transcript records and in-progress iteration state;
- agent lifecycle and activity dispatch;
- browser, terminal, file, generation, and desktop updates;
- replay of restored conversations;
- live-only effects such as audio and resource refreshes;
- preview persistence and global overlays.

This makes behavior difficult to change safely. Live and restored events also
take different paths through the frontend, which creates opportunities for the
two paths to interpret the same event differently.

The refactor should make ownership explicit while keeping the application
functional after every PR.

## Terminology

- **Stream envelope:** The live wire shape containing transport metadata and a
  nested event payload.
- **Conversation event:** The canonical flat event record used by the
  frontend. Stored events already have this shape; live envelopes are
  normalized into it.
- **Transcript model:** The ordered Turns and transcript items shown in the
  main conversation view. `projectTurns` builds this model from event records.
- **Agent model:** Agent identities, parent/child relationships, lifecycle
  status, context usage, and per-agent activity.
- **Workspace model:** Browser tabs and frames, terminal state, file previews,
  generation previews, desktop state, and fullscreen presentation.
- **Session state:** The active conversation ID, draft, streaming status, stop
  status, optimistic user input, and current event records.
- **Catalog state:** The list, folders, titles, pinning, and archival metadata
  for all conversations. This is distinct from the active session.
- **Live-only effect:** A reaction that must happen when an event arrives live
  but must not run during replay, such as playing audio or refreshing a tools
  list.
- **Destination:** Serializable navigation state identifying the visible
  desktop surface and stable entity IDs.

The word “projection” may describe the general event-to-model operation in
architecture discussions. Code should prefer concrete names such as
`projectTurns`, `agentReducer`, and `workspaceReducer` over generic projection
abstractions.

## Design principles

1. **One event vocabulary.** Live and restored data become the same canonical
   conversation event shape before application code interprets them.
2. **One interpretation per concern.** Transcript, agent, and workspace rules
   each have one implementation shared by live delivery and replay.
3. **Replay is deterministic.** Replaying finalized events produces the same
   transcript and agent state as processing those events live.
4. **Effects are explicit.** Replay rebuilds state but never repeats live-only
   effects.
5. **Transport does not know UI semantics.** The stream client yields records;
   it does not update React state or dispatch feature callbacks.
6. **No generic global event bus.** Event flow remains explicit and typed by
   domain responsibility. Components should not subscribe to invisible global
   traffic.
7. **Data and visibility are separate.** Hiding a surface must not destroy its
   session state. Persistent surfaces stay mounted when continuity requires it.
8. **Navigation stores IDs, not entities.** Feature data is resolved from
   feature-owned state using stable IDs.
9. **Contexts provide ownership, not concealment.** A provider should expose a
   coherent model and commands; it should not merely hide a large hook.
10. **No temporary compatibility exports.** Update imports at the same time a
    function moves so obsolete entry points cannot linger.
11. **Every PR is shippable.** Each stage preserves a working application and
    carries validation proportional to its risk.

## Intended end state

### Application ownership

```text
AppProviders
├── ConversationCatalogProvider
├── ConversationSessionProvider
├── AgentProvider
├── WorkspaceProvider
└── DesktopNavigationProvider
    └── DesktopShell
        ├── Sidebar
        ├── MainSurface
        ├── PersistentCustomAppLayer
        └── GlobalOverlays
```

The exact provider nesting may change to avoid circular dependencies, but the
ownership boundaries should remain.

| Area | Owns | Does not own |
| --- | --- | --- |
| Conversation catalog | Lists, folders, titles, pins, archive state | Active stream or draft |
| Conversation session | Active ID, draft, event records, stream lifecycle, conversation commands | Desktop surface selection |
| Agent model | Agent graph, status, context usage, activity | Selected desktop destination |
| Workspace model | Browser, terminal, files, generation, desktop, preview persistence | Transcript structure |
| Desktop navigation | Serializable destination and named navigation commands | Feature entities or event handling |
| Desktop shell | Layout and composition | Wire protocol, event switches, feature state machines |
| Custom app layer | Current app workspace and continuity | Route participation in this refactor |

`DesktopApp` should end as a small composition boundary. It should not parse a
stream, switch on conversation event types, rebuild restored state, manage
browser or terminal protocol details, or pass a large event-callback object into
the conversation hook.

### Event flow

```text
Live /api/chat response
    → conversationClient (request + JSONL transport)
    → normalizeLiveEvent
    ───────────────────────────────────────┐
                                           │
Restored canonical event records ──────────┤
                                           ▼
                    applyConversationEvent(event, source)
                        ├── transcript records/model
                        ├── agent reducer/actions
                        ├── workspace reducer/actions
                        └── live-only effects (source === "live")
```

The dispatcher may call several narrow reducers or action builders. It must not
become a second monolith. Unknown events should be ignored safely by consumers
that do not understand them.

Restored browser and terminal sidecars are snapshots rather than ordinary
append-only transcript records. They should enter through explicit workspace
restore actions, not be disguised as conversation events.

### Conversation session API

Components should consume a session-oriented interface instead of the internals
of `useStreamingChat`:

```text
State/selectors
- activeConversationId
- turns
- draft
- isStreaming
- stopRequested
- stalled

Commands
- sendMessage
- sendNudge
- stopGeneration
- openConversation
- newConversation
- setDraft
```

Transport details, abort controllers, optimistic records, event storage, and
replay mechanics remain private to the session implementation.

### Route-ready navigation without a router

The refactor ends with a serializable destination model and named commands:

```text
{ kind: "chat", conversationId }
{ kind: "network", conversationId, agentId }
{ kind: "settings", tab }
{ kind: "agents", profileId }
{ kind: "routines", routineId, runId }
{ kind: "artifacts", artifactId }
{ kind: "apps" }
```

Commands such as `openConversation`, `openAgent`, `openArtifact`,
`openSettings`, and `goBack` operate on destinations. Components do not call
`setView` or browser history APIs directly.

This stage does not provide URL deep links or browser back/forward behavior. A
future router can implement the same destination and command interface without
requiring feature components to change.

Custom apps remain outside routing for now. They stay in a persistent layer so
switching desktop surfaces does not unnecessarily reset them. A future
validated bridge may call navigation commands such as `openArtifact(id)`.

## Refactor stages

### Stage 1 — Establish the event model

**Status: Complete — PR #196**

- [x] Extract live-envelope normalization.
- [x] Extract deterministic transcript construction.
- [x] Isolate accumulation of the current live iteration.
- [x] Define shared event and transcript-item names.
- [x] Add direct unit coverage with no compatibility exports.
- [x] Run the full UI suite, production build, and full end-to-end suite.

### Stage 2 — Extract the conversation stream client

**Status: Next**

Create a small transport module under
`server/ui/src/features/conversation/transport/`.

- [ ] Move `/api/chat` request construction out of `useStreamingChat`.
- [ ] Keep removal of UI-only attachment preview data at the transport
      boundary.
- [ ] Move `fetch`, abort-signal wiring, `TextDecoder`, JSONL buffering, and
      parsing into the client.
- [ ] Expose an async stream of raw envelopes; do not normalize or interpret
      event types in the client.
- [ ] Preserve ordering, malformed-line behavior, abort behavior, and missing
      response-body behavior.
- [ ] Add unit tests for request shape, arbitrary chunk boundaries, multiple
      records per chunk, split UTF-8 input, malformed lines, empty bodies,
      network failures, and aborts.
- [ ] Leave all React state updates, event handling, frame batching, and effects
      in their current locations for this stage.

**Completion signal:** `useStreamingChat` contains no `/api/chat` fetch,
`getReader`, `TextDecoder`, JSONL buffer, or stream-level `JSON.parse` logic.

### Stage 3 — Separate event application from live-only effects

**Status: Pending**

- [ ] Move the per-event switch out of the transport/session hook.
- [ ] Split event interpretation into narrow transcript, agent, workspace, and
      effect handlers.
- [ ] Pass explicit dependencies to handlers; do not introduce a global event
      bus.
- [ ] Tag application with `source: "live" | "replay"`.
- [ ] Run audio, notifications, resource refreshes, and similar reactions only
      for live delivery.
- [ ] Preserve frame batching and event arrival order for agent activity.
- [ ] Ensure one handler failure cannot corrupt the remainder of a stream.

During this stage, resolve the current retention-policy ambiguity deliberately:

- [ ] Distinguish “used in the current transcript” from “durably replayable.”
- [ ] Reconcile the frontend event-retention set with the backend persistence
      policy, including `error`, `tool_created`, and `context_usage`.
- [ ] Add an automated contract guard so the two policies cannot silently
      drift again.

**Completion signal:** the session hook receives canonical events and delegates
their meaning; it does not contain a large list of event-type branches.

### Stage 4 — Unify live delivery and restored-conversation replay

**Status: Pending**

- [ ] Feed restored records through the same transcript and agent handlers used
      by finalized live records.
- [ ] Replace `_replayEvents` and remove duplicate event-to-agent action rules.
- [ ] Restore browser, terminal, and preview sidecars through explicit
      workspace restore actions.
- [ ] Prevent restored data from triggering live-only effects.
- [ ] Add shared fixtures that are applied once as live input and once as
      restored input.
- [ ] Assert equivalent final transcript, agent graph, activity ordering, and
      relevant workspace state.

The core invariant is:

```text
apply(finalized live events) == apply(the same restored events)
```

### Stage 5 — Introduce the conversation session boundary

**Status: Pending**

- [ ] Introduce `ConversationSessionProvider` and a controller/client boundary.
- [ ] Move active ID, draft, stream lifecycle, pending input, and canonical
      event records behind the session API.
- [ ] Expose focused selectors and commands rather than a large mutable object.
- [ ] Remove the large callback-ref contract between `DesktopApp` and
      `useStreamingChat`.
- [ ] Keep catalog state separate; rename the existing conversations context to
      `ConversationCatalogProvider` when doing so no longer creates churn.
- [ ] Audit the legacy `messages` state and remove it only after all real
      consumers have moved to Turns or agent activity.

**Completion signal:** active-conversation behavior can be mounted and tested
without `DesktopApp`, and desktop layout can be tested without constructing the
stream protocol.

### Stage 6 — Give agent and workspace state clear owners

**Status: Pending**

- [ ] Separate the agent graph/activity model from presentation state such as
      selected agent and visible network surface.
- [ ] Move browser, terminal, file, generation, desktop, and fullscreen
      coordination into a workspace boundary.
- [ ] Extract `PreviewPanel` so it owns the preview mode switch and shared
      fullscreen overlay.
- [ ] Move preview persistence and browser-control coordination out of
      `DesktopApp`.
- [ ] Keep durable workspace state distinct from transient control sessions and
      live frames.

**Completion signal:** `DesktopApp` does not understand browser-tab merging,
terminal restoration, preview sidecars, or fullscreen item kinds.

### Stage 7 — Introduce route-neutral desktop navigation

**Status: Pending**

- [ ] Replace string `view` juggling with the serializable destination model.
- [ ] Add named navigation commands and selectors.
- [ ] Store stable IDs rather than entity objects.
- [ ] Preserve the active conversation while moving between conversation and
      agent-network destinations.
- [ ] Keep custom apps in their persistent non-routed layer.
- [ ] Add reducer tests for transitions, invalid destinations, and back-stack
      behavior.
- [ ] Do not synchronize browser history in this stage.

**Completion signal:** feature components navigate through commands and have no
knowledge of `setView` or browser history.

### Stage 8 — Decompose the desktop shell and finish cleanup

**Status: Pending**

- [ ] Extract `DesktopShell`, `MainSurface`, `PersistentCustomAppLayer`, and
      `GlobalOverlays` as composition components.
- [ ] Move feature-specific loading, empty, and error states into their feature
      boundaries.
- [ ] Preserve intentional mounted-state behavior for the conversation and
      custom-app surfaces.
- [ ] Remove obsolete callbacks, state, imports, comments, tests, and legacy
      helpers after their replacements are proven.
- [ ] Confirm `DesktopApp` is a composition boundary rather than a controller.
- [ ] Run all validation gates below.
- [ ] Delete this plan file in the final PR.

## Validation gates for every stage

Before each PR is considered complete:

- [ ] Add characterization coverage before moving behavior when current tests
      do not protect it.
- [ ] Run all frontend unit/component tests.
- [ ] Run the production UI build.
- [ ] Run the relevant focused end-to-end tests while iterating.
- [ ] Run the complete end-to-end suite before handoff.
- [ ] Confirm live conversation creation, multi-turn use, stop, nudge, errors,
      uploads, agent spawning, conversation restoration, workspace restoration,
      and custom-app continuity still function.
- [ ] Search for obsolete exports, names, and imports instead of leaving
      compatibility aliases.
- [ ] Keep the worktree limited to the intended stage.

## Known risks and safeguards

### Live/replay drift

The same durable event can currently be interpreted by live callback code and
separate replay code. Shared fixtures and common action builders must be in
place before deleting either implementation.

### Event retention drift

The backend persistence policy and frontend retained-event set are not
currently identical. Do not paper over that difference with a broad “all
events are persisted” assumption. Decide which events are durable, which are
snapshot-producing, and which are live-only, then guard the contract.

### Ordering and frame batching

Agent content and activity are batched per animation frame. Moving event logic
must preserve arrival order and guarantee a final flush at turn end and stream
completion.

### Replay effects

Restoring a conversation must not play old audio, repeat notifications, refresh
resources because of historical events, or reopen transient control sessions.

### Mounted-state continuity

The main conversation surface and custom-app workspace have intentional
continuity requirements. Component extraction and navigation changes must not
turn ordinary surface changes into unmount/remount cycles.

### Context proliferation

More providers do not automatically mean better encapsulation. Each provider
must own a coherent domain, expose a small interface, and avoid rerendering the
entire desktop for high-frequency stream updates.

### Router-shaped code without a router

Do not manually mirror destination state into `window.history`. That would be a
partial router with unclear parsing and restoration rules. Finish the
route-neutral destination interface first; add a real router later if desired.

## Explicitly deferred work

These are compatible future directions but are not required to complete this
refactor:

- introducing a frontend router, URL deep links, and browser back/forward;
- allowing custom apps to participate directly in routing;
- adding a validated custom-app navigation bridge;
- splitting conversation and other events into separate backend streams;
- redesigning the backend event wire format;
- replacing persistence storage or sidecar formats;
- broad visual redesign of the desktop.

## Final completion checklist

The refactor is complete when:

- [ ] transport, canonical event application, models, effects, navigation, and
      layout have explicit owners;
- [ ] live and restored events share interpretation code;
- [ ] restored conversations reproduce the expected transcript and agent
      state without replaying effects;
- [ ] `DesktopApp` is a small composition boundary;
- [ ] feature components use named navigation commands with serializable IDs;
- [ ] the application remains ready for a future router without depending on
      one;
- [ ] the full frontend and end-to-end suites pass;
- [ ] obsolete compatibility code and legacy state are removed;
- [ ] this plan file is deleted in the final PR.
