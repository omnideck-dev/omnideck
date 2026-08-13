# Hosted application behavior test

## Purpose

Verify desktop integration and the boundary between the exact hosted loopback
origin and the privileged local setup webview.

The VM suite already proves hosted launch, downloaded/uploaded data transfer,
and returning-user routing. This procedure reviews native picker presentation,
clipboard, browser routing, shortcuts, single-instance focus, and close behavior
that `manual-remainder.json` deliberately records as `not-run`.

## Procedure

1. Start from a completed healthy setup and record the exact dynamic hosted
   origin.
2. Paste plain, multiline, Unicode, and moderately large text from the host
   into OmniDeck. Copy it back and compare exact values.
3. Open the Agents import control and verify the native file picker appears,
   filters for OmniDeck/JSON files, cancels cleanly, and returns focus to the
   app. File transfer and import success are covered by the automated VM suite;
   this step reviews only native picker presentation and focus behavior.
4. Refresh with `Ctrl+R` or `Cmd+R`, then with `F5`. Repeat once during visible
   hosted activity and record whether state loss is expected.
5. Navigate within the exact hosted origin and confirm it remains in the
   OmniDeck window.
6. Click an external HTTPS link and confirm the default system browser opens.
   Repeat with a link requesting a new window.
7. Exercise a controlled non-HTTP(S) link and confirm no external application
   opens.
8. Launch OmniDeck a second time and confirm the existing window is focused
   without a second host process or window.
9. On macOS, verify standard Edit-menu copy/paste accelerators.
10. Close with the window control and the platform keyboard shortcut in separate
   runs. Confirm no OmniDeck host or orphaned sidecar process remains.
11. Relaunch only to confirm the platform focuses the existing/single expected
    application instance; use the automated result for returning-user routing.

## Security observation

Do not add capabilities or expose test-only commands to make these checks
easier. A hosted page gaining access to any Tauri lifecycle command is a
release-blocking failure. Redirect, alternate-port, localhost-lookalike, and
`window.open` cases belong in automated security tests; use this procedure to
confirm visible packaged behavior.
