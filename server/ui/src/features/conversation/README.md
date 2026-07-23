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
  status, context usage, and per-agent activity.
- **Agent activity:** The ordered work attributed to one agent, such as
  reasoning, content, tool calls, spawned agents, file results, and errors. It
  powers the agent network and detail surfaces and is separate from the main
  transcript.
- **Workspace model:** Browser, terminal, file, generation, and remote-desktop
  state associated with a conversation and its agents.
- **One-time action:** Work triggered only when an event arrives live, such as
  playing audio or refreshing a resource list. Restoring saved events must not
  repeat it.
- **Event action plan:** The session, agent, and workspace reducer actions
  built from one canonical event. Live delivery additionally runs one-time
  actions.

The same conversation event may contribute to more than one model. For
example, root-agent output updates both the transcript and the root agent's
activity, while sub-agent output updates agent activity but does not appear as
root transcript output.

## Ownership and flow

`ConversationCatalogProvider` owns conversation lists and list mutations.
`ConversationSessionProvider` owns the open conversation and its commands.
`AgentProvider` owns the agent graph and activity. `WorkspaceProvider` owns
browser, terminal, file, generation, desktop, and preview presentation state.
`DesktopNavigationProvider` owns a serializable destination and named
navigation commands. `App` assembles setup, these state owners, and `Desktop`.

Live data follows this path:

```text
/api/chat
  → chatClient (request and JSONL stream)
  → normalizeLiveEvent (canonical conversation event)
  → getConversationEventActions
      ├── session reducer actions
      ├── agent reducer actions
      └── workspace reducer actions
  → one-time actions (live delivery only)
```

Restoration reads saved canonical events and calls the same
`getConversationEventActions` function. Saved browser and terminal snapshots
and preview metadata become explicit workspace restore actions. Restoration
does not run one-time actions.

Desktop features navigate through commands such as `openConversation`,
`openAgent`, and `openSettings`. The destination contains stable IDs rather
than feature objects. There is no URL synchronization yet; a future router can
implement the same destination and command interface without changing feature
components.
