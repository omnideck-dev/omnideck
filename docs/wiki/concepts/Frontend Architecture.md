---
title: Frontend Architecture
type: concept
tags: [frontend, react, ui, streaming]
created: 2026-07-07
updated: 2026-07-07
verified_commit: 6a5625d
paths:
  - "server/ui/src/"
---

# Frontend Architecture

## Overview

The frontend is a React 18 SPA built with Vite. It connects to the backend via a persistent SSE stream for streaming chat and uses `fetch` for REST calls. CSS Modules are used for component-scoped styles. No TypeScript — plain JSX throughout.

## Component Tree

```
App.jsx                    ← theme detection, renders DesktopApp
└── DesktopApp.jsx         ← main shell: view routing, global state
    ├── Sidebar.jsx        ← nav rail (Chat, Goals/Routines, Agents, Settings)
    ├── ChatPanel.jsx      ← conversation list + active chat view
    │   ├── ChatMessages.jsx
    │   ├── ChatInput.jsx
    │   └── PreviewPanel.jsx  ← browser tabs, terminal, file outputs
    ├── GoalsView.jsx      ← autonomous task management
    ├── AgentNetwork.jsx   ← sub-agent tree visualization
    ├── AgentActivityView.jsx ← per-agent event stream
    ├── SettingsPage.jsx   ← tabbed settings (providers, profiles, integrations, etc.)
    └── SetupWizard.jsx    ← first-run provider/model selection
```

## State Architecture

### AgentState Reducer (`hooks/useAgentState.jsx`)

The single source of truth for all agent runtime state:
- Per-agent browser screenshots (keyed by `agent_id`)
- Per-agent terminal output
- Per-agent file outputs
- Agent hierarchy (parent/child relationships for AgentNetwork)
- Selected agent for detail view

`DesktopApp.jsx` dispatches actions from SSE event callbacks. All preview components read from the reducer.

### AppData Context (`contexts/AppData.jsx`)

Global data loaded at startup: features flags, agent profiles, available models. Shared via React context so all components can access it without prop-drilling.

### Key Custom Hooks

| Hook | File | Role |
|------|------|------|
| `useStreamingChat` | `hooks/useStreamingChat.js` | SSE connection, event parsing, chat send |
| `useAgentState` / `useAgentDispatch` | `hooks/useAgentState.jsx` | Agent tree reducer |
| `usePreviewState` | `hooks/usePreviewState.jsx` | Preview panel open/active tab state |
| `useBrowserTabs` | `hooks/useBrowserTabs.js` | Browser screenshot tab management |
| `useGoals` | `hooks/useGoals.js` | Goals/routines data fetching |
| `useAgentProfiles` | `hooks/useAgentProfiles.js` | Profile CRUD |
| `useStreamingChat` | `hooks/useStreamingChat.js` | Chat streaming and conversation management |

## SSE Event Handling

`useStreamingChat.js` opens a streaming fetch to `POST /api/chat` and parses the JSONL response line-by-line. Each line is a JSON `AgentEvent` object. The hook routes events:

- `content` / `thinking` → append to messages
- `turn_end` → mark turn complete
- `browser_screenshot` → dispatch to agent reducer
- `terminal_output` → dispatch to agent reducer
- `file_output` → dispatch to agent reducer
- `agent_started` / `agent_completed` → dispatch hierarchy update
- `context_usage` → update context meter

## Conversation Resume

On conversation load, the frontend calls `GET /api/conversations/{id}/resume`. The response includes:
- `messages` — full LLM history
- `events` — saved agent events (file outputs, browser screenshots, terminal blocks) for replay into the reducer
- `preview_state` — which files are open in the preview panel

## Where It Lives

| Path | Role |
|------|------|
| `server/ui/src/App.jsx` | Theme detection, root component |
| `server/ui/src/DesktopApp.jsx` | Main shell, view routing, event callbacks |
| `server/ui/src/components/` | All UI components |
| `server/ui/src/hooks/` | Custom React hooks |
| `server/ui/src/contexts/AppData.jsx` | Global app data context |
| `server/ui/src/utils/` | Pure utilities (file types, highlight, clipboard) |
| `server/ui/vite.config.js` | Build config |
| `server/ui/src/__tests__/` | Vitest component tests |

## Key Details

- **Profile selection is per-conversation.** `convProfile` in `DesktopApp.jsx` holds the in-view conversation's profile; it's initialized from the backend on resume, not global.
- **Preview panel** tracks open file tabs separately from browser tabs — both are sub-states of `usePreviewState`.
- **Sidebar navigation** uses `view` state (`'chat' | 'settings' | 'goals' | 'network'`) to switch the main content area. Agent detail is a sub-state of `'network'`.
- **`SetupWizard`** blocks the main UI until `setup_complete` is true (from `GET /api/settings`).

## Open Questions

- No TypeScript; type safety relies on runtime Pydantic validation on the backend and careful prop naming in JSX.
