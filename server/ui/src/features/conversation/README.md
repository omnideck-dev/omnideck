# Conversation frontend vocabulary

These terms describe frontend responsibilities. They do not require matching
backend classes or separate network channels.

- **Stream envelope:** One record yielded by the `/api/chat` response. It
  contains transport metadata and a nested event payload.
- **Conversation event:** The canonical, flat event shape interpreted by the
  frontend. Live stream envelopes are normalized into this shape; saved events
  already use it.
- **Transcript:** The ordered user prompts and agent results shown in the main
  conversation surface. It includes completed and in-progress output, file
  results, and compaction markers. It is a UI model derived from conversation
  events, not the raw event list or an agent's activity log.
- **Turn:** One root-agent run in the transcript, normally beginning with a
  user prompt. A turn contains ordered transcript items such as iterations,
  file results, and compaction markers.
- **Conversation session:** State for the open conversation, including its ID,
  draft, stream lifecycle, pending input, and the event records needed to build
  the transcript.
- **Agent model:** Agent identities, parent-child relationships, lifecycle
  status, context usage, and sub-agent activity.
- **Agent activity:** The ordered work attributed to one agent, such as
  reasoning, content, tool calls, spawned agents, file results, and errors. It
  powers the agent network and detail surfaces and is separate from the main
  transcript.
- **Workspace model:** Browser, terminal, file, generation, and remote-desktop
  state associated with a conversation and its agents.
- **Application effect:** A typed, one-time notification such as requesting
  audio playback or refreshing a resource list. Effects can originate from
  any feature; restoring saved conversation events does not repeat them.

Root-agent activity is projected from its transcript turn instead of retained
twice. Sub-agent output is excluded from the main transcript and remains in the
agent model for the network activity view.

## Ownership and flow

`ConversationCatalogProvider` owns conversation lists and list mutations.
`ConversationSessionProvider` owns the open conversation and its commands.
`AgentProvider` owns the agent graph and sub-agent activity. `WorkspaceProvider`
owns browser, terminal, file, generation, and desktop data by agent.
`AppEffectsProvider` delivers typed one-time effects to feature owners without
retaining them as global state. `AudioPlayer` subscribes to playback effects
and owns its transient player state locally.
`DesktopNavigationProvider` owns serializable navigation requests and named
navigation commands. `useDesktopWindowManager` owns two equivalent tabbed pane
stacks, surface placement and focus, the horizontal split ratio, fullscreen
presentation, and pending focus for restored workspace surfaces. Each surface
has one stable host even when it moves between panes. Custom Apps and workspace
previews retain their feature data in their own owners and contribute
serializable surface descriptions to the window manager. `App` assembles setup,
these state owners, and `Desktop`.

Live data follows this path:

```text
/api/chat
  → chatClient (request and JSONL stream)
  → normalizeLiveEvent (canonical conversation event)
  → mapConversationEventToActions
      ├── session reducer actions
      ├── agent reducer actions
      ├── workspace reducer actions
      └── application effects (live delivery only)
```

Restoration reads saved canonical events and calls the same
`mapConversationEventToActions` function. Saved browser and terminal snapshots
and preview metadata become explicit workspace restore actions. Restoration
ignores application effects.

Desktop features navigate through commands such as `openConversation`,
`openAgent`, and `openSettings`. Sidebar reads that navigation owner directly
instead of sending generic panel identifiers through Desktop. Desktop
interprets navigation requests as surfaces to open or select in the left pane;
any surface can subsequently move to either pane. Destinations and surfaces
contain stable IDs and serializable metadata rather than React content or
feature objects. There is no URL synchronization yet; a future router can
implement the same destination and command interface without changing feature
components.
