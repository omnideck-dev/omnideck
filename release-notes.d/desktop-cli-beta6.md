---
target: desktop
type: fixed
area: setup
---

Desktop now bundles CLI v0.11.0-beta.6, fixing Windows host routing and passing
the actual local app address to the container for browser sign-in callbacks.
Existing instances are recreated once while preserving their data volumes.
MCP integrations will be delivered separately in a future app release.
