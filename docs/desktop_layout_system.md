# Desktop Layout System

This document defines the vocabulary and ownership boundaries for Omnideck's
desktop layout. The current system arranges views in two fixed tab groups,
floating placements, and fullscreen presentation. It intentionally does not
model generic windows or nested layouts yet.

## Vocabulary

### Desktop

The application shell and composition boundary. `Desktop` coordinates
navigation commands, persistence, and the layout renderer, but it does not own
conversation, workspace, artifact, or Custom App data or lifecycle policy.

### Workspace

The runtime resources produced or used by agents while a conversation runs.
Workspace state includes Browser, Terminal, files, generations, and remote
desktop data, organized by agent.

The Workspace domain owns that data. The Desktop may display a workspace
resource, but it does not become the resource's data owner.

### Workspace resource

One agent-associated resource from the Workspace domain, such as Browser or
Terminal. A workspace-resource view carries the conversation, agent, and
resource identity needed to select the domain data.

### View

A serializable description of something currently open on the Desktop. A view
contains stable identity and the metadata needed to select its renderer. It
does not contain React content or placement.

Examples include the Conversation view, an artifact view, a Custom App view,
and a workspace-resource view.

The Artifacts library is one View with the stable ID
`destination:artifacts`. Opening it from Chat applies a transient
`conversationId` filter to that View; opening it globally or clearing the
filter updates the same View rather than opening a second tab. Individual
artifact files are separate durable Views.

### View ID

The stable primary key for one open view. Layout state refers to views by ID so
that moving a view does not change its identity or remount its content.

### View type

The discriminator that selects a view's renderer, such as `conversation`,
`workspace-resource`, `artifact-file`, or `custom-app`.

### Desktop Layout

The presentation system that owns:

- The open-view registry.
- The left and right tab groups.
- Tab order and active-view selection.
- Focus between tab groups and floating views.
- Floating position, size, and stacking.
- The horizontal split ratio.
- Fullscreen presentation.

Desktop Layout does not own domain lifecycle or domain data.

### Tab group

An ordered list of View IDs with one active View ID. Left and right are
equivalent tab groups; either may contain any view.

### Floating view

A view with floating placement metadata: position, size, focus, and stacking.
The current implementation gives each floating placement exactly one view.

### Fullscreen view

A presentation mode layered over a view's existing placement. Exiting
fullscreen reveals the same view in its previous tab group or floating
placement.

### View host

The stable React container for one view. View hosts are layout siblings rather
than children of tab groups. Moving, floating, docking, or maximizing a view
changes its host's presentation without changing its React parent or key.

This stability preserves iframe, editor, and feature-local state.

### View content

The domain-owned React UI rendered inside a View host. The view type selects
the renderer; the renderer reads current data from its domain owner.

### Domain adapter

A domain-specific renderer adapter or command hook at the boundary between a
domain and Desktop. A per-View renderer adapter receives View identity and
reads the rest of its data from the domain's existing contexts. A command
adapter translates an artifact, app, or Workspace resource into a generic View
before crossing into Desktop.

There is no generic `Feature` runtime abstraction. "Domain" names an ownership
boundary; adapters are named for the domain they connect.

### Domain effect

A named, headless component that installs domain lifecycle reactions which
outlive any individual rendered View. For example, Workspace effects react to
root-agent resource availability and to generic View-close announcements.

Domain effects are siblings of `DesktopShell`; they do not wrap the shell or
unrelated domain renderers:

```text
DesktopViewRuntimeProvider
`-- DesktopNavigationProvider
    |-- DesktopDomainEffects
    |   |-- WorkspaceResourceDesktopEffects
    |   |-- CustomAppDesktopEffects
    |   `-- ArtifactDesktopEffects
    `-- DesktopShell
        `-- DesktopViewContent
            `-- one per-View domain adapter
```

### Navigation target

A request to open or select a view. Navigation expresses intent and translates
it directly into View commands; it does not keep a second current-location
store. The focused View's navigation target is the current application
location.

### First-run layout

The setup feature may persist one initial Desktop Layout snapshot before
Desktop mounts. A fresh installation uses this to open the seeded welcome
conversation in one tab group and its dashboard artifact in the other.

This is not a special Desktop mode. The ordinary restore path consumes the
snapshot, and later layout changes overwrite it normally. Setup only writes
the snapshot on the first incomplete-to-complete transition, never replaces an
existing browser layout, and never recreates deleted or archived welcome
content.

## Current model

```text
Domain state
Conversation / Workspace / Custom Apps / Artifacts
                         |
                         v
            Domain adapters and effects
                         |
               open / update / close View
                         |
                         v
+--------------------------------------------------+
| Desktop Layout                                   |
|                                                  |
| Open views                                       |
| Left tab group         Right tab group           |
| Floating placements    Fullscreen presentation   |
+-------------------------+------------------------+
                          |
                          v
                    Stable View hosts
                          |
                          v
                  Domain-owned View content
```

The central rule is:

> A View identifies what is open. Desktop Layout decides where and how it is
> presented. The domain owner supplies the data rendered inside it.

## React adapter boundary

`DesktopViewContent` is a static View-type router. Its interface contains only
the View and its placement metadata:

```text
DesktopViewContent(view, active, tabGroupId)
```

It does not receive conversation sessions, Workspace state, artifact actions,
agent counts, profiles, or Custom App catalogs. Instead, each domain provides a
Desktop adapter that:

1. Reads data from that domain's existing React contexts.
2. Converts domain resources into serializable View descriptions.
3. Uses the narrow Desktop View command context for placement changes.
4. Supplies domain data and actions to its own renderer.

Long-lived synchronization is installed as a named headless domain effect, not
as a provider wrapped around `DesktopShell`.

Every domain adapter follows one file-level public convention:

```text
features/<domain>/<Domain>DesktopAdapter.jsx
  export function <Domain>DesktopEffects()      // headless installation
  export function use<Domain>DesktopActions()   // commands into Desktop
  export default function <Domain>DesktopView() // per-View renderer
```

The lower-level `use<Domain>DesktopViews` hooks remain private effect
implementations. Callers import cross-boundary actions and renderers from the
adapter, so adding another domain does not introduce a fourth adapter shape.

The cross-boundary command is generic:

```text
openView(view, { tabGroupId, activate })
```

Desktop commands must not grow domain-specific methods such as
`openArtifact(artifact)` or `openCustomApp(app)`. Those conversions belong to
the Artifact and Custom Apps adapters respectively.

Close and toolbar-action coordination is generic too. Desktop announces which
View descriptors are closing and which declared View action was requested.
Feature owners interpret those announcements; Desktop never switches on a View
type to decide domain policy.

## Persistence and rehydration

Desktop Layout persists durable View identity, not copies of domain records.
The persisted core is the View ID, type, label, icon, closability, and the
smallest domain key needed to resolve the live record. For example, a Custom
App persists its slug and an Artifact persists its artifact ID or legacy file
path. Transient fields such as iframe reload signals and declared runtime
actions are never saved.

On restore, each domain adapter resolves its own keys:

- Custom Apps resolve slugs through the live catalog and close Views for apps
  that no longer exist.
- Artifacts resolve IDs or legacy output paths through the Artifact store,
  rebuild the live file descriptor, and close Views whose artifact is gone.
- Workspace resource Views already carry their complete durable conversation,
  agent, and resource identity; their renderer reads live data from Workspace.

This keeps storage generic and makes deletion/staleness policy the
responsibility of the domain that can answer it.

## Lifecycle boundaries

View placement and domain lifecycle are separate:

- Switching, creating, or closing a conversation removes its
  workspace-resource views.
- Restoring historical conversation data does not recreate previously closed
  workspace-resource views.
- Root-agent Browser and Terminal availability may open an unfocused view in
  the tab group opposite Conversation.
- Sub-agent workspace resources open only through an explicit user action.
- Artifact and Custom App views remain open until explicitly closed or until
  their owning resource is no longer available.
- The Artifacts library may switch between a conversation filter and all
  artifacts without changing View identity or placement.
- Closing or moving a view never deletes its domain data.

## Tab commands

The active tab exposes one compact overflow button. It opens the same command
menu that is available by right-clicking any tab or by using the keyboard
context-menu shortcut. Move, float, fullscreen, reload, and close commands are
therefore represented once rather than as a row of inline tab buttons.

## Current limitations

- Only one globally active conversation is supported.
- There are exactly two docked tab groups.
- Each floating placement contains one view.
- Floating tab groups, nested layouts, snapping, and multiple native browser
  windows are future work.

## Future windowing direction

`Window` is reserved for a future layout container that can host a tab group or
nested layout:

```text
Window
`-- Tab group
    |-- View A
    `-- View B
```

When floating tab stacks or nested layouts are implemented, Desktop Layout may
gain explicit Window entities and a Window Manager. Introducing those entities
now would encode behavior that the product does not yet support.

## Naming rules

- Use **View**, not Surface, for open renderable identities.
- Use **View ID**, not Surface ID.
- Use **View type**, not Surface kind.
- Use **Tab group**, not Pane, for the left and right tab hosts.
- Use **Desktop Layout**, not Window Manager, for the current placement owner.
- Use **Workspace resource**, not Conversation execution, for agent Browser and
  Terminal views.
- Use concrete domain names instead of a generic Feature abstraction.
- Do not add lifecycle grouping metadata to views. Domain adapters should
  explicitly identify the views they update or close.

## Follow-up simplifications

These are implementation observations, not additional concepts:

- Move View factories and restore validators fully into their owning domains.
  Persistence now uses a validator registry rather than encoding payload
  schemas itself, but the registry and factories are still centralized in
  `desktopViews.js`.
- Give Custom App view instances unique IDs. Slug-based IDs currently limit an
  app to one simultaneous open instance.
- Consider splitting `TabbedPane` into a reusable tab strip and an optional
  content owner. It no longer emits an empty content node for Desktop tab
  groups, but its API still supports both roles.
- Replace Workspace-specific host test attributes with a generic View-owned
  test metadata convention before changing the existing E2E selectors.
- Revisit whether the focused Terminal should disable Browser control while a
  Browser view remains visible.
