---
target: app
type: changed
area: integrations
---

Integration access is now stored and enforced as an explicit per-tool
allowlist. Existing connections migrate automatically, and brokered model
providers remain available without appearing as tool integrations. Integration
setup now uses a modal catalog, connection, tool-selection, and review flow;
cancelling removes setup-owned credentials, while connected accounts can
replace credentials without losing supported tool choices.
Google connections now use the scopes actually granted during authorization
when determining which tools are available.
Connection details now open on Tools, with renaming and reconnecting together
under Connection. Tool pickers use a consistent background for controls and rows.
