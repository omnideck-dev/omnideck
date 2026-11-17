---
target: app
type: fixed
area: startup
---

Report failed saved-settings upgrades to the CLI and desktop startup recovery
screen, with safe diagnostic details and a retry that preserves existing data.
This requires CLI v0.11.0-beta.9 or Desktop v0.1.0-beta.15; earlier consumers
continue to use their existing readiness checks.
