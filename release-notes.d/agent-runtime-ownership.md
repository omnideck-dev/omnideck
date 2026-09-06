---
target: app
type: fixed
area: agents
---

Nudges now target only live agents in the selected conversation. Cancelling a
routine task stops its agents and releases their resources before task completion.
Runtime shutdown also waits for pending event writers to finish cancellation cleanup.
