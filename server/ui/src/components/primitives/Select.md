# Select

`Select` is the canonical ordinary dropdown for the SIGNAL interface. Both its
trigger and its listbox are rendered by the application so sizing, caret,
surface, option rows, selection, focus, disabled state, and light/dark themes
remain consistent in Tauri's WKWebView, WebView2, and WebKitGTK hosts. Because
the listbox is portaled, the primitive explicitly carries the trigger's
computed typography into the menu.

The primitive keeps focus on its select-only combobox trigger and exposes the
active option with `aria-activedescendant`. It supports pointer selection,
Arrow Up/Down, Home/End, Enter/Space, Escape, typeahead, focus return,
click-outside dismissal, viewport collision, and reduced motion. Automatic-width
instances size to their longest option, then shrink when their container cannot
fit that width; truncated labels retain their full value as hover text. Supply
an `ariaLabel` or `ariaLabelledBy` on every instance.

Consumers can set `--select-width` for a fixed width or
`--select-max-width` to cap intrinsic sizing while retaining responsive
shrinkage.

Use `ModelPicker` only for the richer searchable provider/model workflow.
Native `<select>` elements are prohibited by the accompanying source-policy
test because their opened menus are host-rendered and cannot satisfy the shared
visual contract.
