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
replace credentials without changing their saved tool choices, even when OAuth
scopes narrow. Vault metadata upgrades run before brokers start and leave
encrypted credentials unchanged. Older permission-format requests are rejected
with a prompt to refresh the app.

**Action required for previously read-only HTTP integrations:** migration
disables the API tool for these integrations while preserving their configuration
and credentials. To resume using the tool, explicitly enable it under
Settings → Integrations → Change tools. Enabling it permits both read and write requests,
subject to the upstream token's permissions; the old read-only restriction is no
longer available. Previously read/write HTTP integrations retain API tool access.

Google connections now use the scopes actually granted during authorization
when determining which tools are available.
Connection-list responses now use a single `connections` field. Integration
catalog listings retain `integrations`; saved connection IDs and existing agent
tool arguments are unchanged.
Connection details now show a read-only summary of selected tools. Change tools
and Rename open focused editing dialogs; Connection settings provides
service-specific actions to update credentials. Tool pickers have searchable,
collapsible groups and a consistent background for controls and rows.
Integration discovery now refreshes in the background and after connection edits.
Each agent run keeps its starting tool availability, while later runs pick up
changes; revoked permissions remain enforced when tools are called.
Tool selections now update without restarting the connection or interrupting
already-running calls. Failed live updates stop the connection rather than
restore revoked access. Healthy brokers now accept credential updates without
restarting. Rejected replacements keep the existing connection; credential
activation may interrupt an in-progress call. Generic HTTP and model-provider
credentials are checked for valid configuration, not guaranteed upstream access.
