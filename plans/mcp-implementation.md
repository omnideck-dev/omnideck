# Remote MCP integration — implementation

Base: `origin/main` at `bd943fbf` (merged integration refactor, PR #415).
Worktree: `mcp-integrations`; branch: `feat/mcp-integrations`.

## Review snapshot — October 5, 2026

This branch is a work-in-progress review snapshot, not a release or a merge
request. It includes the remote MCP/Slack implementation, tests, and the
[revised agent/skill/category mockup](../artifacts/category-design/agent-skill-tools-sonnet55-grounded.html)
created with Claude Sonnet 5.5 (high reasoning). The mockup uses synthetic data;
it is not connected to the running app.

The proposed per-integration categories, direct agent category selections,
and their migration are **not implemented**. The design retains the existing
agent editor and Settings navigation, uses the term Integrations consistently,
and removes the redundant approval-summary disclosure. Agents would combine
direct selections with categories inherited from skills. The owner approved
documenting a one-time migration from old capability selections to all
already-approved tools on the mapped existing connections.

Known frontend review follow-ups remain: recovery when OAuth succeeds but the
connection-list reload fails; preserving requested scopes on generic MCP
reconnect; and visible recovery for Google OAuth polling network errors.
These should be addressed before treating the implementation as release-ready.

Before publishing this snapshot, `just check`, the focused MCP backend suite,
and 56 frontend integration/model-picker tests passed. This is not a fresh
full end-to-end or packaged-app qualification. Runtime state, credentials,
raw model transcripts, and local verification logs are excluded from the commit.

## Product boundary

One generic remote Streamable HTTP broker implementation, with a separate
broker process per connection. OAuth belongs in the first user-visible release.
Slack is the first live reference server; the broker must remain vendor-neutral.
Do not add stdio execution until its sandbox is designed.

Reuse integration setup, tool selection, exact operation grants, and the shared
brokering lifecycle. Preserve the boundary between integration operations and
LLM-facing adapters. No capability/read-write tiers, safety hints, recommended
tools, operation versioning, output-schema metadata, or placeholder consumer
authorization model. Do not expose IDs or protocol badges as UI decoration.
New tools remain unselected. Runtime insufficient-scope reauthorization is
deferred; initially surface a useful error without silently starting consent.

## First milestone: official SDK compatibility

Pinned `mcp==2.2.0`; the SDK owns MCP framing, negotiation and OAuth wire details.
Do not build a parallel protocol client. Compatibility tests live under
`tests/integration/brokering/mcp`, and use only disposable loopback fixtures.

Implemented tests:

- Official SDK server/client over actual HTTP with protocol `2026-07-28`.
- Automatic fallback against a `2025-11-25` wire fixture.
- Empty catalogs are successful connections.
- Paginated discovery retains local references and nested input schemas.
- OAuth discovery, DCR/CIMD selection, PKCE S256, resource indicators, and stored
  token reuse. Refresh writes the rotated refresh token back to storage.
- State/issuer mismatches prevent token exchange.
- Pre-registered public client (no DCR) using the real loopback callback,
  including issuer rejection before token exchange.

The initial integration preview is now implemented: Slack and generic MCP catalog
presets share one broker, setup coordinator, encrypted OAuth persistence and
dynamic agent-tool projection. Catalog entries are gated on the runtime's trusted
`OMNIDECK_EXTERNAL_URL`; published desktop beta.12 with CLI beta.6 now supplies
the verified published-port configuration. This does not establish end-to-end
MCP OAuth in the published app, which still lacks this pending implementation.
Live Slack consent, PKCE exchange and discovery succeeded in the
manual container. SDK-only tests remain compatibility gates,
distinct from the added real supervisor and browser lifecycle tests.

## Implemented callback transport

`server._mcp_oauth_callback.listen_for_mcp_oauth` owns a short-lived IPv4
loopback listener and one `MCPOAuthCallback`. Its redirect handler adapter arms
the callback with the SDK-generated state before presenting the authorization
URL; `wait_for_result` returns the single browser response to the SDK. The SDK
then validates the issuer and performs PKCE token exchange. Tests cover early
returns, malformed/duplicate parameters, wrong state/Host, replay, denial,
expiry, cancellation, concurrent returns, occupied ports, and listener cleanup.
Access logging is disabled on this dedicated listener, and responses neither
reflect provider data nor claim that credential persistence has completed.

The standalone helper is **host-local**, not a container forwarding solution.
Normal app setup now routes callbacks to owned receivers through the configured
published app address. `MCPSetupManager` owns cancellation and connection commits;
`BrokerManager` owns encrypted persistence and non-interactive token rotation.
Callbacks cannot derive their address from untrusted request Host headers.

## Implemented preview

- Public HTTPS Streamable HTTP, with pinned/validated DNS, strict no-redirect
  policy and bounded discovery/results. Loopback HTTP is test-gated.
- OAuth discovery/DCR or preregistered public clients, PKCE, issuer binding,
  absolute-expiry restoration, and durable refresh-token rotation. Explicit
  requested scopes are preserved despite the SDK's discovery default.
- Existing modal connection/tools/review flow, per-tool selection and grants,
  reconnect, cancellation cleanup, and shared Google/MCP OAuth polling.
- Immutable dynamic input schemas and connection-bound `SchemaTool` adapters;
  no output-schema validation, sampling or elicitation.
- SDK transport lifetime stays in one owner task so supervisor credential
  prepare/activate/discard can safely run in different tasks.
- Real HTTP/Unix socket/vault/subprocess coverage plus actual browser OAuth,
  selection and cancellation tests. The user's live Slack credentials remain
  in the manual container's encrypted vault, never in fixtures or source.

## Release follow-ups

Internal-app setup validation: `just check`, 785 targeted backend tests, all
883 frontend tests, and 15 integration-settings browser E2E tests passed.
Manual verification at port 9094 confirmed saved Client ID reuse and cancellation
without changing the current live connection's 27 selected tools. This was not
a new OAuth consent or live Slack operation test. The companion CLI passed
`make verify` and the Debian product VM lane (portable contract, attended TUI,
unattended lifecycle, callback environment assertion, and cleanup). Windows and
macOS runtime behavior and the newly pinned desktop package were subsequently
qualified for desktop beta.12. Available native public-package lanes passed,
with captured callback origins matching final published ports. Windows used
the explicitly certified WSL 2.7.14 compatibility baseline; current WSL
onboarding remains a separate issue (#424).

The user selected organization-owned internal apps as the first shipping path.
Slack now has an explicit connection adapter with collapsible instructions, a
copyable manifest (MCP, PKCE, rotation, user scopes, configured callback), and a
required public Client ID. Reconnect preloads that ID through a supervisor
allowlist; no tokens or client secrets reach the form. Google and Slack share
instruction primitives and the existing OAuth lifecycle, not a backend-driven
universal form. `OMNIDECK_SLACK_CLIENT_ID` no longer supplies a shared default.
A Marketplace-approved registration remains the future easy path; there is no
public-distribution workaround for the internal development app.

1. **Completed:** release and bundle the companion CLI change
   (`feat/mcp-callback-origin`). It
   now derives the callback origin from its published host port and bumps the
   container layout to 2 so reconciliation recreates older containers without
   deleting volumes. Unit tests cover default/custom ports and all platform
   argument paths, plus one-time layout upgrade. Hardware tests assert the
   environment in the running fixture. Immutable CLI v0.11.0-beta.6 is bundled
   in published desktop v0.1.0-beta.12 (release PR #425, merge `ef486ad3`),
   and the local DEB update is verified. This runtime prerequisite is complete;
   the MCP implementation itself remains unmerged and unreleased. Keep the
   trusted-configuration availability gate and never infer the address from an
   untrusted request Host header.
2. **Completed October 2, 2026 (UTC):** the owner confirmed fresh Slack consent.
   Reconnect preserved the connection and its 27 selected tools. Live calls
   through `IntegrationService` as the unprivileged app user found
   `#all-omnideck-community` with `slack_search_channels` and read two messages
   with `slack_read_channel` using the returned channel ID. Both returned
   `isError: false`. No Slack mutations were performed; message contents and
   credentials are not retained in this plan. An initial search for `general`
   returned no matches; an empty search was rejected by Slack's parameter
   validation. Public-channel listing supplied the real channel name before
   the successful search/read. This supersedes the earlier two-scope
   `missing_scope` attempt, not merely the sign-in/discovery check.
3. Verify dynamic schemas against live model providers. Deterministic schema
   and execution tests are not evidence of every provider's schema support.

## Slack development reference

Use the separate internal `omnideck MCP development` Slack app in the
`Omnideck Community` workspace. With explicit user approval, Slack MCP and PKCE
are enabled. The initial request used only `channels:read` and `channels:history`.
The app settings subsequently showed additional configured scopes; do not
silently modify them. The user has now requested the full Slack integration:
the explicit policy in `integrations/catalog/slack.py` requests all 30 documented
MCP user scopes. Existing tokens are not widened until the user approves new
consent. There are no bot scopes. The localhost 9094 callback is registered;
live consent/token exchange and two-tool discovery succeeded for the prototype.
Leave the existing `Omnideck (Larry)` bot
unchanged. Confirm any further access changes and live consent with the user.

- Endpoint: `https://mcp.slack.com/mcp` (Streamable HTTP).
- Pre-registered public client with PKCE S256; Slack does not support DCR.
- PKCE was enabled after confirmation of its one-way nature without Slack support.
- Full preset scopes cover search, history, messaging, reactions, people, files,
  canvases, lists and channel creation. Private conversations and writes require
  fresh Slack consent and explicit local tool selection. Exercise search and
  selected reads after consent; deterministic fixtures cover mutation without
  sending real Slack messages. Own-registration is now the default setup path.
- Registered **development-only** callback:
  `http://localhost:9094/api/integrations/mcp/oauth/callback`. The host-local
  listener helper is implemented; the running preview uses the app callback
  route. This URL is registered with Slack. Bind any eventual published port to loopback only and verify reachability
  from the user's browser before starting consent. Do not turn this dev port
  into a product-wide requirement; packaged desktop callback handling remains
  an explicit implementation decision.
- The current `/api/integrations/oauth/callback` and `OAuthIntegrationManager`
  are Google-specific. Reuse lifecycle concepts, not Google's token exchange
  or request-Host-derived redirect construction. MCP callback origins must
  come from trusted runtime configuration and bind to the initiating session.
- Prove the actual user-token endpoint accepts the public-client flow before
  treating Slack compatibility as complete: its discovery metadata advertises
  `client_secret_post`, while its desktop docs describe secretless PKCE.
  Do not ship a shared client secret or globally ignore metadata mismatches.
- Keep real tokens out of fixtures, source, logs, and browser-facing responses.
  Live consent follows a tested callback and encrypted persistence path; do
  not install merely to obtain a token for manual copying.

## Remaining boundaries

- Desktop-host callback versus container-only callback: derive addresses from
  trusted configuration. No hosted redirect service is assumed or authorized.
- Registration: pre-registered clients where available, CIMD only with a real
  published metadata URL/callback arrangement, DCR fallback where supported.
- Private endpoints require a separate explicit policy; the implemented public
  HTTPS policy only permits loopback HTTP with the existing test flag.
- Discovery is refreshed on reconnect, not through live catalog notifications.
  Newly discovered tools are not automatically granted.
- Existing customized skills need the Connected tools category enabled; the
  bundled default assistant includes it for new installations.
- Runtime insufficient-scope challenges fail without interactive authorization
  or tool-call replay. Reconnect is the explicit recovery path.

## Validation

Local preview validation includes `just check`, the full frontend suite
(875 tests), Python unit/application integration suites (browser-tool suite
excluded), and the full app E2E suite (330 tests). The latter includes real
browser OAuth, tool selection and cancellation against disposable upstream
fixtures. Real-process integration tests cover vault persistence, grants,
restart, reconnect, rotated-token persistence, and rejected refresh without
new consent. Final counts are recorded in the implementation handoff.

The complete app E2E run preceded the last catalog-bound and supervisor-metadata
consistency hardening; the MCP browser tests are rebuilt and rerun afterward.
Live Slack authorization, discovery, channel search and a selected channel read
have since been exercised. Packaged-desktop end-to-end MCP OAuth and live model
provider schema handling remain separate checks; the companion runtime's
published callback-origin configuration is verified.

Full Slack preset validation: 93 focused MCP backend tests, 882 frontend tests,
three MCP browser E2E tests and `just check` passed. The browser reconnect test
verifies the same connection ID, preserved selections and explicit selection of
newly discovered tools. The updated manual container on localhost:9094 retains
the user's credentials and chats. Fresh consent and the bounded live search/read
check are now complete as recorded above. The preview was restored as
`omnideck_mcp_manual`, bound only to `127.0.0.1:9094`, using the existing saved
state. Resume verification passed `just check` and 49 focused MCP tests.

## References checked at implementation start

- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [OAuth client integration](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/oauth-clients.md)
- [Streamable HTTP client](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md)
- [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Slack MCP server and scope mapping](https://docs.slack.dev/ai/slack-mcp-server/)
- [Slack desktop PKCE requirements](https://docs.slack.dev/authentication/using-pkce/)

Historical design notes are retained under `archive/mcp-design`; this plan and
the user's subsequent decisions take precedence over them.
