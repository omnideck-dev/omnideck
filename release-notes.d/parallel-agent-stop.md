---
target: app
type: fixed
area: agents
---

Stopping parallel sub-agents now waits for every child's cleanup before ending
the run, keeping their completion events in conversation history and preventing
the Agent Network from leaving stopped agents marked as running.
