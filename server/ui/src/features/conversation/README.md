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
- **Event delivery:** Giving one canonical event to the session, agent, and
  workspace handlers. Live delivery additionally runs one-time actions.

The same conversation event may contribute to more than one model. For
example, root-agent output updates both the transcript and the root agent's
activity, while sub-agent output updates agent activity but does not appear as
root transcript output.
