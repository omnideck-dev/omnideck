# SIGNAL design language — agent index

Agent-readable companion to the human showcase at `docs/design/design_language.html`
and the tokens in `server/ui/src/global.css`. The HTML renders every pattern for
people; this file is the index an agent greps **before** building UI.

## How to use this (rules)

1. **Before writing any UI, look for a canonical component or class here and reuse it.**
   Most "new" UI is an existing primitive + tokens.
2. **Never hardcode colors, spacing, radii, font families/sizes, or z-index** —
   use the tokens below. They auto-swap for dark mode via `[data-theme="dark"]`.
   Exact control geometry documented by the showcase (for example the 32px input
   height) may be copied when no component owns it.
3. **No generic primitive exists for some patterns** (Input, Cards, Empty State,
   Form Section). For those, replicate the documented CSS class **into your component's
   `.module.css`** (copy the spec from the showcase / an existing component) — that's
   the house pattern, not a deviation.
4. **Shared components own their appearance and interaction states.** Do not override
   their palette, geometry, hover, or disabled styles in feature CSS. Improve the
   shared component when the design changes, so existing consumers adopt it too.
   Keep feature styles to composition (spacing and placement). Discuss any necessary
   exception and document why; structural options such as modal content layout
   belong in the shared API rather than a CSS override.
5. The HTML showcase is the source of truth for exact spec values; this file points
   you at the right pattern by name.
6. **Organize with spacing and typography before adding borders or surface layers.**
   One enclosing boundary is usually enough. Use `--border-subtle` for necessary
   internal separators; do not box every subsection or alternate surface levels
   just to divide content. Preserve input boundaries, readable controls, hover
   feedback, and visible keyboard focus.
7. These are app-wide design rules, not a record of which feature adopted them
   first. Update the relevant rule and showcase when a pattern changes; do not
   append contradictory feature-specific exceptions. Existing screens may lag
   behind the guide; apply the rules to new work and screens being revised.

## Reusable components (import and use directly)

Primitives live in `server/ui/src/components/primitives/`; the rest in
`server/ui/src/components/`.

| Need | Component | Import | Use when |
|---|---|---|---|
| Text button | `Button` | `primitives/Button.jsx` | `filled` for one primary action/surface; `ghost` for quiet secondary actions, including Cancel beside Save and collection bulk actions; `outline` when a peer action needs stronger definition; `danger` for destructive actions. The API defaults to `outline`, so choose the variant explicitly. Icon via children: `<Button><Icon/> Label</Button>`. For async actions pass `loading` and optionally `loadingLabel`. |
| Icon-only button | `IconButton` | `primitives/IconButton.jsx` | `size="sm"` (28px), `md` (32px) beside text buttons; icon as child. Match ghost buttons: `--radius-md`, `--text-secondary`, `--surface` hover. |
| Icon picker popover | `IconPickerPopover` | `primitives/IconPickerPopover.jsx` | Curated Bootstrap icon selection shared by folders and profile identity controls. Anchor it with `anchorRef` or `anchorRect`; supply `icons`, `current`, `onPick`, and `onClose`. |
| Select / dropdown | `Select` | `primitives/Select.jsx` | Canonical application-rendered select-only combobox. Pass `options`, `value`, `onChange`, and an accessible label. Native `<select>` is prohibited because host-rendered menus cannot satisfy the shared visual contract. |
| Two-click destructive | `ConfirmButton` | `primitives/ConfirmButton.jsx` | delete/disconnect where a modal is overkill; arms on first click, fires on second. In action menus use `appearance="menuItem"`: quiet red text until armed, then filled danger. Standalone buttons retain their tinted resting background. |
| Search field | `SearchInput` | `primitives/SearchInput.jsx` | `value`, `onChange(string)`, `placeholder`, `ariaLabel`, `testId`, `clearable`, `disabled`, `className`. Canonical `.input` + leading glyph + focus glow |
| Ordinary dropdown | `Select` | `primitives/Select.jsx` | Canonical body-font, 32px select-only combobox. Consumers may specialize font size and width, but not family or height. Supports keyboard navigation, typeahead, portaled viewport-aware menus, and full-label hover text. |
| Brand tabs | `BrandTabs` | `primitives/BrandTabs.jsx` | §14 uppercase primary tabs within a panel or settings page; `tabs=[{id,label,count?,disabled?,panelId?}]`, `activeTab`, `onTabChange`, `ariaLabel`, `idBase`. `idBase` links each tab to its tabpanel. Distinct from `LibraryHeader` and desktop `TabStrip` |
| View tabs + scoped search | `LibraryHeader` | `primitives/LibraryHeader.jsx` | §27: in-content view switch (`views=[{id,label,count}]`, `activeView`, `onViewChange`, `searchValue`, `onSearchChange`, `actions`) |
| Inline feedback message | `Callout` | `primitives/Callout.jsx` | §11 feedback (info/success/warning/danger banners) |
| Modal scaffold | `Modal` | `primitives/Modal.jsx` | scrim + centered panel with Esc/backdrop dismiss + dialog semantics; pass `onClose`, `children`, optional `width`/`labelledBy`/`testId`. Caller supplies the contents. Default padding suits simple dialogs; `layout="contained"` supplies a padding-free, viewport-bounded flex shell for headers/scrolling bodies/footers. Both use the same shared surface |
| Status / tag pill | `Badge` | `components/Badge.jsx` | Discrete tags and counts needing an enclosing shape; not the default for connection status. Routine connection health stays quiet; problems use plain icon + text (see Exception-first status). `variant`: `neutral`(default)`\|success\|info\|warning\|danger`. Monospace, 10px, radius-sm. |
| List row | `ListItem` | `components/ListItem.jsx` | `active`, `onClick`, optional `icon`, `name`/`description`/`badges` (or `children`). Rounded boundary with accent outline + muted background on selection; no feature-level restyling |
| Expandable selected row | `ExpandableSelectionRow` | `components/ExpandableSelectionRow.jsx` | Selected skills, tools and integrations with wrapping `name`/`description`, leading `icon`, disclosed `children` and required `onRemove`. One centered header aligns the chevron and separate remove button in matching 32px slots. Row owns expansion and appearance; parent owns selection. |
| Selected tool grid | `SelectionToolList` | `components/skills/SelectionToolList.jsx` | Read-only responsive columns inside an expanded selection row. MCP tools show titles only; native integration operations retain short descriptions. Clipped labels reveal plain text on hover, focus or tap through the shared Popover. No individual-tool disclosure or modal. |
| Master-detail layout | `SplitPanel` | `components/SplitPanel.jsx` | `SplitPanel` + `.List` + `.Detail`; `.Header` takes a title as children and optional `actions`. Owns outer `--sp-5` gutters: hosts must not add duplicate outer padding. Spaced columns with one divider; list is 34% (min 260px), 250px below 860px. Below 640px, one stacked scroll area. **List-on-left/detail-on-right only** |
| Connection status | `ConnectionStatus` | `components/ConnectionStatus.jsx` | Existing explicit status/test-result component used by provider settings. Do not add it as permanent healthy reassurance on revised screens; use Exception-first status below. Keep Configured distinct from verified Connected. Existing consumers have not all migrated. |
| Draggable split resizer | `SplitHandle` | `components/SplitHandle.jsx` | `onDrag(position)` — for resizable splits (e.g. chat + preview) |
| Tab strip | `TabStrip` | `components/TabStrip.jsx` | Accessible tab chrome with overflow scrolling, keyboard selection, close controls, and per-tab action menus. Pass `tabs`, `activeTab`, `onTabChange`, and `onCloseTab`; content is owned separately. |
| Sortable data table | `SortableTable` | `primitives/SortableTable.jsx` | sticky header with click-to-sort columns (caret) + hover/active rows. Presentational — caller sorts the rows + owns `sort`. `columns=[{key,header,sortable,render,cellClassName,headerClassName,revealOnHover}]`, `rows`, `rowKey`, `onSort`, `onRowClick`, `rowClassName`, `activeRowKey`, `rowTestId`, `testId`. |
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
| Editor toolbar | `Editor Toolbar` | Leading ghost Back; trailing status, dirty-only ghost Discard, filled Save, then overflow. Anchor Save and overflow so transient feedback and Discard do not move them. New items use Create plus the item name and omit saved-item actions. Below 640px put status on a second, start-aligned line. Show success only after saving, fading out by 3s (no animation under reduced motion); unsaved/error feedback persists. |
| Action menu | `Action Menu` | Use `Popover` with menu semantics; move initial focus through its `onOpen` callback after positioning makes the surface visible. `Button variant="menuItem"` and `ConfirmButton appearance="menuItem"` own the row appearance. Left-aligned icon/label, full-width 32px rows, readable primary text and surface hover. Caller supplies menuitem roles and keyboard handling: arrows/Home/End, Escape returning focus, Tab leaving the menu. Destructive actions last after a subtle divider; keep the menu open during confirmation. Use an ellipsis on actions opening another dialog. |
| Text input | `Inputs` | `.input` spec (or use `SearchInput` if it's a search) |
| Modal / dialog | `Modal / Dialog` | Use `Modal` for the enclosing surface. Separate header/body with spacing, not a mandatory rule; use `--border-subtle` if a footer divider is needed. Do not add nested boxes for ordinary content. Pair a filled primary action with ghost Cancel. Older hand-rolled modals have not all migrated. |
| Data table | `Tables` | use the **`SortableTable` primitive** (sticky `--canvas` header, click-to-sort columns, `--border-subtle` row separators). Caller sorts the rows + owns the sort state |
| Contained collection picker | `Collection Picker` | Toolbar and rows share `--elevated`, with a `--border-subtle` separator. Standalone collections may have an outer border; inside an enclosing modal/panel, omit the nested border and corner treatment. Keep toolbar outside the row scroller; use `SearchInput` and ghost bulk actions. No shared collection-toolbar primitive yet. |
| Card | `Cards` / `Display Card` / `File Output Card` | For distinct objects, use `--elevated` + `--border` + `--radius-lg`; hover lift only when interactive. Use spacing and headings for ordinary subsections, not nested cards. |
| Empty state | `Empty State` | centered icon + message, `--text-tertiary` |
| Chip / tag | `Chip / Tag` | Small pill for discrete metadata/tags; use `Badge` when appropriate, not as a wrapper for every status label. |
| Exception-first status | `Status Vocabulary` | Routine connection health stays quiet: no permanent Connected label, checkmark, pill or dot. List rows keep their useful secondary description when healthy; replace it with a decorative warning triangle and specific recovery text when attention is needed. Use `--warning`, inherited body typography and `--sp-1` gap, without background, border or pill. Selection styling remains independent. Unknown states must stay visible, not imply health. In details, explain the problem and recovery in a Callout without repeating a header badge. Keep unrelated errors distinct. Explicit user-requested connection-test results may still confirm success. |
| Section / form section | `Sections` / `Form Section` / `Settings Row` | Group related settings with headings and spacing. Keep the main task visible; start optional, infrequently used settings collapsed under a descriptive disclosure. Do not hide required inputs or actionable errors; point to recovery when it sits inside a collapsed section. |

## Action hierarchy rationale

MCP tools use their supplied title, falling back to the tool name. Model-facing
descriptions are not UI copy: omit them from setup/edit pickers, selected-tool
lists, tooltips, and UI search. Preserve them unchanged for model use. Native
integration operations may retain their curated short descriptions.

Enabled ghost actions use `--text-secondary`, not tertiary text, to avoid looking
disabled. Menu rows use `--text-primary` because their lack of a button boundary
already provides secondary emphasis. Icon and text controls share corner and
hover treatments instead of looking like unrelated families.

Expandable selection rows are disclosures, not navigation links. Keep titles
in `--text-primary` on hover; use `--surface` for the disclosure button's hover
background and brighten its chevron to `--text-primary`. Use `--radius-md` and
retain the accent keyboard-focus outline. The separate remove button keeps its
own shared IconButton interaction states.

**Deliberate exception to the tinted destructive-button resting state:** inside
an action menu, Delete uses a red icon/label on a transparent background. A filled
Delete among quiet peers overemphasizes the destructive choice. Keep the existing
filled-danger confirmation state and two-activation protection. This exception
belongs to `ConfirmButton`, not a feature-level style override.

Editor feedback communicates changes, not permanent reassurance: leave a clean
editor quiet; only a successful save earns a short confirmation. Save remains
explicit, and failed saves must not clear the draft or unsaved warning.

## Token cheatsheet (`global.css`)

All values come in light ("Blueprint", default) and dark ("Terminal", `[data-theme="dark"]`).
Use the variable, never the literal.

- **Surfaces (depth):** `--canvas` (page) · `--surface` (raised) · `--elevated` (cards/menus)
- **Text:** `--text-primary` · `--text-secondary` · `--text-tertiary` · `--text-on-accent`
- **Borders:** `--border` · `--border-subtle` · `--border-strong`
- **Accent:** `--accent` · `--accent-hover` · `--accent-muted` (tint bg) · `--accent-glow` (focus ring)
- **Status:** `--success`/`--success-muted` · `--warning`/`--warning-muted` · `--danger`/`--danger-muted` · `--scrim` (modal backdrop)
- **Shadows:** `--shadow-sm` · `--shadow-md` · `--shadow-lg` · `--shadow-glow`
- **Radius:** `--radius-sm` 4 · `--radius-md` 6 (buttons, inputs, selects, dropdowns) · `--radius-lg` 8 · `--radius-xl` 12 · `--radius-full`
- **Spacing (4px base):** `--sp-1`..`--sp-12` (4,8,12,16,20,24,32,40,48)
- **Z-index:** `--z-sticky` 10 · `--z-flyout` 100 · `--z-toast` 1000 · `--z-modal` 9999 · `--z-wizard` 10000 · `--z-tooltip` 10001
- **Fonts:** `--font-brand` (mono wordmark/uppercase) · `--font-body` (UI) · `--font-code` (code/paths)
- **Type sizes:** `--font-size-label` 10 · `--font-size-caption` 11 · `--font-size-small` 12 · `--font-size-body` 13 · `--font-size-ui` 14 · `--font-size-heading` 18
- **Layout:** `--header-height` 36 · `--sidebar-width` 44 · `--flyout-width` 270
- **Motion:** `--ease` · `--ease-out` (use for transitions)
