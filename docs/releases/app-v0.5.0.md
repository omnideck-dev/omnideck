# omnideck app 0.5.0

## Added

- **Mobile:** omnideck now works on phone-sized screens. The chat composer no longer gets clipped below the visible viewport, only one workspace pane is shown at a time instead of an unreachable second one, and the sidebar starts collapsed to save space. Desktop stays a two-pane layout, unchanged.
- **Pwa:** omnideck can now be installed to a phone or laptop home screen/app launcher for a standalone, browser-chrome-free window with its own icon.

## Fixed

- **Agents:** Oversized tool output is now saved to a temporary file with a preview and path, keeping large results out of conversation context while allowing focused inspection with existing tools. File searches now return partial results when output or execution limits are reached, and stuck searches are terminated.
