# omnideck app 0.3.0

This release improves agent cancellation and browser cleanup, and bundles the
code font so page loading no longer depends on Google Fonts.

## Fixed

- **Agents:** Nudges now target only live agents in the selected conversation.
  Cancelling a routine task stops its agents and releases their resources before
  task completion. App shutdown waits for pending event writers to finish cleanup.
- **Browser:** Chat browsers remain available between turns, while delegated-agent
  browsers close with their executions. Conversation removal and routine completion
  wait for browser cleanup. These lifetimes also apply when agents run without
  the HTTP server.
- **Interface:** The code font now ships with the app, so unavailable Google Fonts requests no longer delay page loading.
