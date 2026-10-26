---
target: app
type: fixed
area: browser
---

When the agent's browser fails to open a page in a new tab, the empty tab is
now closed instead of being left behind, so failed attempts no longer use up
the agent's open-tab limit.
