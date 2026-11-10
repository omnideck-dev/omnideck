---
target: app
type: fixed
area: browser
---

Browser tools now reconsider embedded content after the host page finishes
loading, so a slowly loading dominant iframe does not leave its controls hidden
behind a cached view of the host page.
