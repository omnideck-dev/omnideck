# SIGNAL design language — agent index

Agent-readable companion to the human showcase at `docs/design/design_language.html`
and the tokens in `server/ui/src/global.css`. The HTML renders every pattern for
people; this file is the index an agent greps **before** building UI.

## How to use this (rules)

1. **Before writing any UI, look for a canonical component or class here and reuse it.**
   Most "new" UI is an existing primitive + tokens.
2. **Never hardcode colors, spacing, radii, fonts, or z-index** — use the tokens below.
   They auto-swap for dark mode via `[data-theme="dark"]`.
3. **No generic primitive exists for some patterns** (Select, Modal, Table, Input,
   Cards). For those, replicate the documented CSS class **into your component's
   `.module.css`** (copy the spec from the showcase / an existing component) — that's
   the house pattern, not a deviation.
4. **If you must deviate, say so in a comment** explaining why (the concept, not a
   file reference), so the next reader knows it was deliberate.
5. The HTML showcase is the source of truth for exact spec values; this file points
   you at the right pattern by name.

## Reusable components (import and use directly)

Primitives live in `server/ui/src/components/primitives/`; the rest in
`server/ui/src/components/`.

| Need | Component | Import | Use when |
|---|---|---|---|
| Text button | `Button` | `primitives/Button.jsx` | variants: `outline` (default), `filled` (one primary/surface), `ghost` (quiet), `danger`. Icon via children: `<Button><Icon/> Label</Button>` |
| Icon-only button | `IconButton` | `primitives/IconButton.jsx` | `size="sm"`; icon as child |
| Two-click destructive | `ConfirmButton` | `primitives/ConfirmButton.jsx` | delete/disconnect where a modal is overkill; arms on first click, fires on second |
| Search field | `SearchInput` | `primitives/SearchInput.jsx` | `value`, `onChange(string)`, `placeholder`, `ariaLabel`, `testId`, `clearable`, `className`. Canonical `.input` + leading glyph + focus glow |
| View tabs + scoped search | `LibraryHeader` | `primitives/LibraryHeader.jsx` | §27: in-content view switch (`views=[{id,label,count}]`, `activeView`, `onViewChange`, `searchValue`, `onSearchChange`, `actions`) |
| Inline feedback message | `Callout` | `primitives/Callout.jsx` | §11 feedback (info/success/warning/danger banners) |
| Modal scaffold | `Modal` | `primitives/Modal.jsx` | scrim + centered panel with Esc/backdrop dismiss + dialog semantics; pass `onClose`, `children`, optional `width`/`labelledBy`/`testId`. Caller supplies the contents. **New** — older modals still roll their own (not yet retrofitted) |
| Status / tag pill | `Badge` | `components/Badge.jsx` | `variant`: `neutral`(default)`\|success\|info\|warning\|danger`. Monospace, 10px, radius-sm |
| List row | `ListItem` | `components/ListItem.jsx` | `active`, `onClick`, `name`/`description`/`badges` (or `children`). 2px accent left-border on active |
| Master-detail layout | `SplitPanel` | `components/SplitPanel.jsx` | `SplitPanel` + `.List` + `.Detail`. List is 35% (min 280/max 420), detail fills. **List-on-left/detail-on-right only** |
| Draggable split resizer | `SplitHandle` | `components/SplitHandle.jsx` | `onDrag(position)` — for resizable splits (e.g. chat + preview) |
| Tabbed preview shell | `PreviewPanel` | `components/PreviewPanel.jsx` | `tabs`, `activeTab`, `onTabChange`, `onCloseTab`, `children` |
| Sortable data table | `SortableTable` | `primitives/SortableTable.jsx` | sticky header with click-to-sort columns (caret) + hover/active rows. Presentational — caller sorts the rows + owns `sort`. `columns=[{key,header,sortable,render,cellClassName,headerClassName,revealOnHover}]`, `rows`, `rowKey`, `onSort`, `onRowClick`, `rowClassName`, `activeRowKey`, `rowTestId`, `testId`. Used by the artifacts hub + goals |
| Render any file | `FilePreview` | `components/FilePreview.jsx` | `item={{filename, content_type, path}}`, optional `fullscreen`/`onFullscreen`/`onClose`. Self-contained (fetches + renders md/html/img/pdf/text) |
| On/off switch | `ToggleSwitch` | `components/ToggleSwitch.jsx` | boolean setting (34×20 pill, accent when on) |
| Status dot | `StatusDot` | `components/StatusDot.jsx` | running/complete/error indicator |
| Toasts | `ToastProvider` / `useToast` | `components/ToastProvider.jsx` | transient notifications |

## CSS-only patterns (no component — replicate the class in your `.module.css`)

Copy the spec from the showcase section named below (or from a component that already
uses it). These have **no shared primitive yet** — replicating is the established
pattern; consider extracting a primitive when 3 or more copies exist.
| Pattern | Showcase section | How |
|---|---|---|
| **Select / dropdown** | `Select` | native `<select className={styles.select}>` + a module `.select` (32px, `appearance:none` + chevron SVG, `[data-theme="dark"] .select{background:var(--surface)}`, focus ring). Used by SystemSettings, ProfileSelector, ArtifactsHubView. **No `Select` primitive exists.** |
| Text input | `Inputs` | `.input` spec (or use `SearchInput` if it's a search) |
| Modal / dialog | `Modal / Dialog` | prefer the new `Modal` primitive for new modals. The older ones still roll their own scrim+panel (`var(--scrim)` + `var(--z-modal)` panel, `--elevated`/`--border`/`--shadow-lg`/`--radius-lg`) — see AddProviderModal; not yet retrofitted |
| Data table | `Tables` | use the **`SortableTable` primitive** (sticky `--canvas` header, click-to-sort columns, `--border-subtle` row separators). Caller sorts the rows + owns the sort state |
| Card | `Cards` / `Display Card` / `File Output Card` | `--elevated` + `--border` + `--radius-lg`; hover lift + `--shadow-lg` |
| Empty state | `Empty State` | centered icon + message, `--text-tertiary` |
| Chip / tag | `Chip / Tag` | small pill (prefer `Badge` for status/tags) |
| Brand tabs | `Tabs` (§14) | uppercase brand tab bar (distinct from `LibraryHeader`'s mixed-case view tabs) |
| Section / form section | `Sections` / `Form Section` / `Settings Row` | settings layout scaffolding |

## Token cheatsheet (`global.css`)

All values come in light ("Blueprint", default) and dark ("Terminal", `[data-theme="dark"]`).
Use the variable, never the literal.

- **Surfaces (depth):** `--canvas` (page) · `--surface` (raised) · `--elevated` (cards/menus)
- **Text:** `--text-primary` · `--text-secondary` · `--text-tertiary`
- **Borders:** `--border` · `--border-subtle` · `--border-strong`
- **Accent:** `--accent` · `--accent-hover` · `--accent-muted` (tint bg) · `--accent-glow` (focus ring)
- **Status:** `--success`/`--success-muted` · `--warning`/`--warning-muted` · `--danger`/`--danger-muted` · `--scrim` (modal backdrop)
- **Shadows:** `--shadow-sm` · `--shadow-md` · `--shadow-lg` · `--shadow-glow`
- **Radius:** `--radius-sm` 4 · `--radius-md` 6 (buttons, inputs, selects, dropdowns) · `--radius-lg` 8 · `--radius-xl` 12 · `--radius-full`
- **Spacing (4px base):** `--sp-1`..`--sp-12` (4,8,12,16,20,24,32,40,48)
- **Z-index:** `--z-sticky` 10 · `--z-flyout` 100 · `--z-toast` 1000 · `--z-modal` 9999 · `--z-wizard` 10000 · `--z-tooltip` 10001
- **Fonts:** `--font-brand` (mono wordmark/uppercase) · `--font-body` (UI) · `--font-code` (code/paths)
- **Layout:** `--header-height` 36 · `--sidebar-width` 44 · `--flyout-width` 270
- **Motion:** `--ease` · `--ease-out` (use for transitions)
