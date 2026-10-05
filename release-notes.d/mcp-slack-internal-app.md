---
target: app
type: added
area: integrations
---

Connect remote MCP servers and select individual tools for omnideck to use.
Slack setup supports an organization-owned internal app, with a copyable app
manifest and guided OAuth sign-in using its public Client ID. Reconnecting
reuses saved registration details and preserves tool selections; newly
discovered tools remain disabled until selected. Credentials stay in the local
encrypted vault. Shared Marketplace-backed Slack sign-in is not included yet.

MCP currently requires a runtime that supplies its local browser callback
address. The sign-in browser must run on the same computer as omnideck; remote
server/browser setups are not yet supported. Slack workspace policies and app
approval still apply.
