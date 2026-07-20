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
- one-time actions such as audio and resource refreshes;
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
  frontend. Saved events already have this shape; every live envelope is
  normalized into it before UI code interprets the event.
- **Transcript model:** The ordered Turns and transcript items shown in the
  main conversation view. `projectTurns` builds this model from event records.
- **Agent model:** Agent identities, parent/child relationships, lifecycle
  status, context usage, and per-agent activity.
- **Workspace model:** Browser tabs and frames, terminal state, file previews,
  generation previews, desktop state, and fullscreen presentation.
- **Saved workspace snapshots:** Backend persistence used to rebuild workspace
  state without replaying every live update. Browser and terminal snapshots
  have dedicated files; preview state is stored in conversation metadata.
- **Session state:** The active conversation ID, draft, streaming status, stop
  status, optimistic user input, and event records needed by the open
  conversation.
- **Catalog state:** The list, folders, titles, pinning, and archival metadata
  for all conversations. This is distinct from the active session.
- **One-time event action:** Work that should happen once when an event arrives
  live but must not run during replay, such as playing audio or refreshing a
  tools list.
- **Destination:** Serializable navigation state identifying the visible
  desktop surface and stable entity IDs.

The word “projection” may describe the general event-to-model operation in
architecture discussions. Code should prefer concrete names such as
`projectTurns`, `agentReducer`, and `workspaceReducer` over generic projection
abstractions.

## Design principles

1. **One event vocabulary.** Live and restored data become the same canonical
   conversation event shape before the frontend handles them.
2. **One interpretation per concern.** Transcript, agent, and workspace rules
   each have one implementation shared by live delivery and replay.
3. **Replay is deterministic.** Replaying saved events produces the same
   durable transcript and agent state as processing the finalized live event
   sequence. In-flight presentation and one-time actions are deliberately
   outside this guarantee.
4. **One-time actions are explicit.** Replay rebuilds state but never repeats
   work that should only happen during live delivery.
5. **Transport does not know UI semantics.** The stream client yields records;
   it does not update React state or dispatch feature callbacks.
6. **Backend durability and UI retention are separate.** The backend decides
   what can be restored. The frontend decides what the open session needs to
   keep in memory. Their type lists are not expected to be identical.
7. **No generic global event bus.** Event flow remains explicit and typed by
   domain responsibility. Components should not subscribe to invisible global
   traffic.
8. **Data and visibility are separate.** Hiding a surface must not destroy its
   session state. Persistent surfaces stay mounted when continuity requires it.
9. **Navigation stores IDs, not entities.** Feature data is resolved from
   feature-owned state using stable IDs.
10. **Contexts provide ownership, not concealment.** A provider should expose a
    coherent model and commands; it should not merely hide a large hook.
11. **No temporary compatibility exports.** Update imports at the same time a
    function moves so obsolete entry points cannot linger.
12. **Every PR is shippable.** Each stage preserves a working application and
    carries validation proportional to its risk.

## Intended end state

### Application ownership

```text
AppProviders
├── AgentProvider
├── WorkspaceProvider
├── ConversationCatalogProvider
├── ConversationSessionProvider
├── DesktopNavigationProvider
└── DesktopShell
    ├── Sidebar
    ├── MainSurface
    ├── PersistentCustomAppLayer
    └── GlobalOverlays
```

This shows ownership, not required React nesting. The exact nesting should be
chosen from actual data dependencies, with separate state and command contexts
where high-frequency updates would otherwise rerender unrelated desktop UI.

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
    → chatClient (POST /api/chat + JSONL transport)
    → normalizeLiveEvent
    ├── applyConversationEvent(event)
    └── runOneTimeEventActions(event)

Saved canonical event records
    └── applyConversationEvent(event)
            ├── conversation session changes
            ├── agent actions
            └── workspace actions

Saved browser and terminal snapshots plus preview metadata
    └── explicit workspace restore actions
```

`applyConversationEvent` coordinates focused state handlers; it does not
contain all event behavior itself. State handlers receive only canonical events
and current state, not a delivery-source flag. They may produce plain reducer
actions or call a small, explicit interface. A failure in one concern must not
prevent the other concerns from seeing the same event, and unknown events
should be ignored safely.

The live intake path invokes `runOneTimeEventActions`; the restore path does
not. Live-only deltas and finalized records are already distinct event types.
For example, `content` updates in-progress output and `iteration` finalizes or
replaces it. Applying a saved `iteration` with no in-progress output produces
the same final state without branching on where it came from.

Browser and terminal sidecars are backend snapshot files, not frontend state
owners. Preview state is stored in conversation metadata. All three should be
converted into explicit workspace restore actions rather than disguised as
conversation events.

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
- newConversation
- setDraft
```

Transport details, abort controllers, optimistic records, event storage, and
replay mechanics remain private to the session implementation. Loading a saved
conversation is an internal session command used by the navigation/shell
integration; feature components use the navigation command
`openConversation(id)` rather than calling the loader directly.

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

### Stage 2 — Extract the chat transport client

**Status: Complete — PR #201**

Create a small transport module under
`server/ui/src/features/conversation/transport/`.

- [x] Move `/api/chat` request construction out of `useStreamingChat`.
- [x] Keep removal of UI-only attachment preview data at the transport
      boundary.
- [x] Move `fetch`, abort-signal wiring, `TextDecoder`, JSONL buffering, and
      parsing into the client.
- [x] Expose an async stream of raw envelopes; do not normalize or interpret
      event types in the client.
- [x] Preserve ordering, malformed-line behavior, abort behavior, and missing
      response-body behavior.
- [x] Add unit tests for request shape, arbitrary chunk boundaries, multiple
      records per chunk, split UTF-8 input, malformed lines, empty bodies,
      network failures, and aborts.
- [x] Leave all React state updates, event handling, frame batching, and effects
      in their current locations for this stage.

**Completion signal:** `useStreamingChat` contains no turn-start `/api/chat`
fetch, `getReader`, `TextDecoder`, JSONL buffer, or stream-level `JSON.parse`
logic.

### Stage 3 — Separate state changes from one-time actions

**Status: Complete — PR #202**

- [x] Split the existing callback block into tested agent, workspace, and
      one-time action handlers.
- [x] Normalize each live envelope once before any UI concern interprets it.
- [x] Move the remaining event-type decisions out of the session hook into
      focused session, agent, and workspace state handlers.
- [x] Pass canonical events directly to state handlers; do not thread delivery
      source through state interpretation or add it to event records.
- [x] Prefer plain reducer actions or narrow handler interfaces over another
      large callback object; do not introduce a global event bus.
- [x] Keep the one-time action runner separate and invoke it only from live
      intake for audio, notifications, resource refreshes, and similar work.
- [x] Preserve frame batching and event arrival order for agent activity.
- [x] Isolate failures per concern so one handler cannot skip other handling
      for the current event or stop later stream records.

**Completion signal:** the session hook receives canonical events and hands
them to focused handlers; it does not contain a large list of event-type
branches.

### Stage 4 — Define the restore contract and unify event interpretation

**Status: Pending**

- [ ] Make backend persistence the single durability policy; do not claim the
      frontend's in-memory retention set mirrors it.
- [ ] Have the resume API return the saved canonical events needed to rebuild
      the UI without maintaining a second, silently drifting replay allowlist.
- [ ] Decide and test the intended behavior of `error`, `tool_created`, and
      `context_usage`: errors should survive when they belong in the saved
      transcript, restored tool events must not repeat one-time work, and agent
      context state must have an explicit restore policy.
- [ ] Feed restored records through the same transcript and agent action rules
      used by finalized live records.
- [ ] Replace `_replayEvents` and remove duplicate event-to-agent action rules.
- [ ] Restore browser and terminal snapshots plus preview metadata through
      explicit workspace restore actions.
- [ ] Keep the restore path from invoking the one-time action runner.
- [ ] Add backend contract coverage for persistence and the resume payload
      rather than asserting that backend and frontend type sets are equal.
- [ ] Add shared fixtures that are applied once as live input and once as
      restored input.
- [ ] Assert equivalent final transcript, agent graph, activity ordering, and
      restorable workspace state.

The core invariant is:

```text
durable state after finalized live events
    == state after restoring the corresponding saved events and sidecars
```

Transient stream progress, one-time actions, and workspace state that is
deliberately not saved are outside this equality.

### Stage 5 — Give agent and workspace state clear owners

**Status: Pending**

- [ ] Keep agent identity, graph, lifecycle, context usage, and ordered activity
      in the agent owner.
- [ ] Move browser, terminal, file, generation, desktop, and fullscreen state
      out of the agent reducer and into a workspace owner keyed by stable agent
      and conversation IDs.
- [ ] Move selected-agent and visible-network state out of the agent model;
      keep it in a small presentation boundary until navigation owns it.
- [ ] Extract `PreviewPanel` so it owns the preview mode switch and shared
      fullscreen overlay.
- [ ] Move preview persistence and browser-control coordination out of
      `DesktopApp`.
- [ ] Keep durable workspace state distinct from transient control sessions and
      live frames.
- [ ] Split state and command contexts, or use focused selectors, where stream
      frequency would otherwise rerender unrelated desktop surfaces.

**Completion signal:** `DesktopApp` does not understand browser-tab merging,
terminal restoration, saved preview metadata, or fullscreen item kinds.

### Stage 6 — Introduce the conversation session boundary

**Status: Pending**

- [ ] Introduce `ConversationSessionProvider` around a focused session
      controller; the `/api/chat` transport remains `chatClient`.
- [ ] Move active ID, draft, stream lifecycle, pending input, and current event
      records behind the session API.
- [ ] Let the session apply event actions to the agent and workspace owners
      directly instead of receiving a large callback-ref contract from
      `DesktopApp`.
- [ ] Expose focused state and commands rather than a large mutable object.
- [ ] Keep catalog state separate; rename the existing conversations context to
      `ConversationCatalogProvider` when doing so no longer creates churn.
- [ ] Audit the legacy `messages` state and remove it only after all real
      consumers have moved to Turns or agent activity.

**Completion signal:** active-conversation behavior can be mounted and tested
without `DesktopApp`, and desktop layout can be tested without constructing the
stream protocol.

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

## Validation gates

During development of every stage:

- [ ] Add characterization coverage before moving behavior when current tests
      do not protect it.
- [ ] Run all frontend unit/component tests.
- [ ] Run the production UI build.
- [ ] Search for obsolete exports, names, and imports instead of leaving
      compatibility aliases.
- [ ] Keep the worktree limited to the intended stage.

Only after explicit confirmation that a PR is ready to merge:

- [ ] Run relevant focused end-to-end coverage when it provides useful failure
      isolation, then run the complete end-to-end suite once as the merge gate.
- [ ] Confirm live conversation creation, multi-turn use, stop, nudge, errors,
      uploads, agent spawning, conversation restoration, workspace restoration,
      and custom-app continuity still function.

Do not run end-to-end tests during ordinary iteration unless explicitly
requested. Record the latest completed merge-gate run in the PR handoff.

## Known risks and safeguards

### Live/replay drift

The same durable event can currently be interpreted by live callback code and
separate replay code. Shared fixtures and common action builders must be in
place before deleting either implementation.

### Durability and UI retention confusion

The backend persistence policy and frontend in-memory event set serve different
purposes and are not currently identical. Name each policy for what it owns.
Decide which events are saved, which are snapshot-producing, which are
live-only, and which the open UI must retain. Guard resume behavior at the API
boundary instead of requiring unrelated type sets to match.

### Ordering and frame batching

Agent content and activity are batched per animation frame. Moving event logic
must preserve arrival order and guarantee a final flush at turn end and stream
completion.

### Actions during restore

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

### Provider ordering and circular dependencies

Navigation needs to open conversations, the session applies agent and workspace
updates, and workspace selection follows the visible agent. Keep feature data
owners independent and connect them through commands at the composition edge.
Do not let one provider import another merely to reach mutable state when a
stable ID or narrow command is sufficient.

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
- adding a backend `memory_changed` event so the Memory view can refresh after
  a successful agent-side mutation; automatic refresh is intentionally disabled
  until that event exists;
- redesigning the backend event wire format;
- replacing persistence storage or sidecar formats;
- broad visual redesign of the desktop.

## Final completion checklist

The refactor is complete when:

- [ ] transport, event handling, models, one-time actions, navigation, and
      layout have explicit owners;
- [ ] live and restored events share interpretation code;
- [ ] restored conversations reproduce the expected transcript and agent
      state without repeating one-time actions;
- [ ] `DesktopApp` is a small composition boundary;
- [ ] feature components use named navigation commands with serializable IDs;
- [ ] the application remains ready for a future router without depending on
      one;
- [ ] the full frontend and end-to-end suites pass;
- [ ] obsolete compatibility code and legacy state are removed;
- [ ] this plan file is deleted in the final PR.
