# Select

`Select` is the canonical ordinary dropdown for the SIGNAL interface. Both its
trigger and its listbox are rendered by the application so sizing, caret,
surface, option rows, selection, focus, disabled state, and light/dark themes
remain consistent in Tauri's WKWebView, WebView2, and WebKitGTK hosts.

The primitive keeps focus on its select-only combobox trigger and exposes the
active option with `aria-activedescendant`. It supports pointer selection,
Arrow Up/Down, Home/End, Enter/Space, Escape, typeahead, focus return,
click-outside dismissal, viewport collision, and reduced motion. Supply an
`ariaLabel` or `ariaLabelledBy` on every instance.

Use `ModelPicker` only for the richer searchable provider/model workflow.
Native `<select>` elements are prohibited by the accompanying source-policy
test because their opened menus are host-rendered and cannot satisfy the shared
visual contract.
