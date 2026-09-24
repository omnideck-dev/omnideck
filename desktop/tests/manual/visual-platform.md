# Visual and platform-fit test

Review the real packaged application on every supported primary desktop OS.
Capture screenshots for each setup phase and any defect.

- Light and dark appearance, including changing the OS theme while open.
- 100%, 125%, 150%, and 200% scaling where supported.
- At each application zoom level, open a tab actions menu and an HTML/file
  preview. Confirm the menu remains attached to its tab, the preview fills its
  pane, no content shifts into an otherwise blank region, and resetting zoom
  restores the original layout. The Linux and Windows packaged lanes
  automate the measurable viewport, menu-anchor, iframe, and window-size
  checks. On macOS, perform those checks manually because the physical host's
  Accessibility driver cannot deliver a trusted Command-key zoom shortcut;
  never infer a pass from unchanged screenshots. Exercise representative zoom-in and
  zoom-out levels; extreme zoom remains a user choice and can be recovered with
  Ctrl/Cmd+0.
- Minimum window size, common laptop resolutions, and resizing during setup and
  after the hosted view opens.
- Multi-monitor movement, especially between displays with different DPI.
- Native close, minimize, maximize, taskbar, dock, launcher, installer, and
  uninstall icons.
- Keyboard-only navigation, visible focus, selection, focus order, contrast,
  and setup status announcements.
- Native select/dropdown closed-state and popup styling compared with the
  established Electron appearance; record platform webview differences rather
  than accepting them as equivalent from DOM assertions alone.
- macOS menus and Intel/Apple Silicon package behavior.
- Linux launcher integration for AppImage, DEB, and RPM on the claimed desktop
  environments; record X11 or Wayland and WebKit versions.
- Cold/warm launch impression, shutdown latency, idle CPU/memory, sleep/wake,
  and network-transition behavior.

Record subjective friction even when a step technically succeeds. A visual or
platform-fit pass requires a human judgment; screenshots alone do not produce
one.
