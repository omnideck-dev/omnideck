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

Discovered tool definitions are saved with connection metadata, separately from
encrypted credentials and tool approvals. Existing MCP connections migrate
automatically without changing approvals or requiring sign-in again.

MCP requires `OMNIDECK_EXTERNAL_URL` on both the app and supervisor. Desktop
v0.1.0-beta.15 supplies a localhost callback address automatically. For sign-in
from another device, configure an origin reachable from that browser and
register its exact callback URL with the provider when required. Slack
workspace policies, app approval, and provider redirect rules still apply.
