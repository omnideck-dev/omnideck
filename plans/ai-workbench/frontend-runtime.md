# Frontend Runtime

> Browser-side containment and hosting design for app frontends. This doc keeps
> the v1 solution simple: sandboxed app frame, parent-owned bridge, tiny SDK,
> tight CSP, and clear risk language for imported apps.

## Relationship To Other Designs

[bundle-format.md](bundle-format.md) defines the saved app version and
`frontend/` layout. [app-router.md](app-router.md) defines the backend invoke
route for public app callables. [callable-runtime.md](callable-runtime.md)
defines backend callable execution and isolation. [feature-flags.md](feature-flags.md)
defines release gates and disabled behavior for app frames and builder preview.

This document owns browser/app-frame containment only. It does not own:

- callable process isolation,
- package dependency installation,
- core storage/file/http/Drive permissions,
- bundle hashes and import/export archives,
- app manager UX and visual mockups.

Those concerns live in the runtime, core callable, bundle format, and UX docs.

## Security Concerns Owned Here

The frontend runtime should address these browser-side concerns:

- app JS must not call arbitrary Omnideck `/api/*` routes,
- app JS must not gain Omnideck UI same-origin authority,
- app JS must not bypass XSRF protections by setting trusted headers directly,
- app JS must not see credentials, cookies, host paths, raw logs, or server
  internals,
- app JS should run under a tight CSP,
- imported apps should show clear "this contains code" risk language,
- future file upload/download exchange must use explicit handles, not raw paths.

The v1 use case is primarily a user building their own app with the agent. That
lets us keep the design practical without pretending imported apps are harmless.
Imported apps are allowed only with explicit user review and acceptance.

## V1 Decision

Use a sandboxed app frame plus parent bridge.

```text
Omnideck shell page
  - trusted same-origin UI
  - owns session/XSRF authority
  - renders app chrome and app identity
  - hosts parent bridge

Sandboxed app frame
  - serves saved app frontend files
  - runs app JS
  - cannot call arbitrary Omnideck APIs
  - asks parent bridge to invoke public app callables
```

The app frame does not directly call:

```text
/api/settings
/api/integrations
/api/conversations
/api/apps/{app_id}/invoke/{route}
```

Instead, app JS calls a tiny SDK:

```js
const result = await omnideck.invoke("list_backlog", { status: "todo" });
```

The parent bridge validates the message source and forwards the request to the
app router:

```text
POST /api/apps/{app_id}/invoke/{route}
```

The bridge must also attach a server-minted, per-frame app capability token. The
token is bound server-side to one app id, one active app version or draft id, one
frame id, and the allowed app route namespace. The app frame never receives this
token. The app router rejects invoke requests whose token is missing, expired, or
bound to a different app than the `app_id` route parameter. This gives app-to-app
authorization a server-side check instead of relying only on bridge code.

Frame creation and serving are feature-flag gated. If `ai_workbench.enabled` or
`ai_workbench.runtime_enabled` is off, the trusted shell should not open app
frames and the backend frame routes must return `FEATURE_DISABLED`. If
`ai_workbench.builder_enabled` is off, the shell should hide builder preview
entry points. Existing app data and saved versions remain intact while gated.

## Browser Compatibility Target

Support current modern evergreen browsers: recent Chrome, Edge, Firefox, and
Safari. Do not design for legacy browsers, embedded webviews with stale engines,
or Internet Explorer-era behavior.

Within that target, prefer the browser primitives with the widest mature support:

- sandboxed iframes,
- `postMessage` between parent and frame,
- ordinary script/CSS/image/font loading from the app bundle,
- CSP headers,
- parent-owned `fetch` to Omnideck routes.

Avoid making v1 depend on narrower or newer browser features such as fenced
frames, credentialless iframes, service workers inside app frames, cross-origin
isolation headers, import maps, browser storage partitioning behavior, or
browser-native file system APIs. Those can be considered later only for a
specific app capability.

Implementation should test the containment contract in the latest stable
Chrome/Edge, Firefox, and Safari before locking the literal iframe attributes
and CSP header values. If one browser requires a different asset-serving detail,
keep the security behavior the same: app code runs in a sandboxed opaque-origin
frame, cannot call arbitrary Omnideck APIs, and reaches Omnideck only through the
parent bridge.

Potential incompatibilities and implementation traps:

- `postMessage` events from an opaque-origin sandbox may have origin `"null"`.
  The parent bridge must validate `event.source`, the expected frame instance,
  request ids, and an initialization token or `MessageChannel`; it must not rely
  only on `event.origin`.
- CSP source matching for bundled assets under an opaque sandbox should be
  verified in every target browser. If `script-src 'self'` or other `'self'`
  sources do not behave consistently for the serving approach, use explicit
  asset URLs, nonces, or hashes while keeping `connect-src 'none'`.
- Browser storage inside the app frame, including `localStorage`,
  `sessionStorage`, IndexedDB, Cache Storage, and service workers, should be
  treated as unavailable for v1. Some browsers may throw security errors rather
  than returning a usable store.
- Module scripts are broadly available in the target browsers, but app bundles
  should avoid import maps and dynamic remote imports for v1. A classic script
  bundle is the lowest-risk baseline.
- Data URLs and font loading can differ across browser/CSP combinations. Keep
  the default asset set small, and verify data images/fonts in Safari as well as
  Chromium and Firefox.
- Since `allow-downloads`, `allow-forms`, `allow-popups`, and top navigation are
  omitted, app UI that expects native downloads, form submits, OAuth popups, or
  full-page redirects will fail by design. Route those workflows through parent
  bridge extensions only after requirements are clear.
- App frame routes must not send headers such as `X-Frame-Options: DENY` or a
  conflicting `frame-ancestors` policy that prevents the trusted Omnideck shell
  from embedding the app.
- Cookies and SameSite behavior should not be part of the app-frame contract.
  The app frame should not need cookies; the trusted parent bridge owns session
  and XSRF authority.

## Why Not Same-Origin App HTML

Same-origin app HTML is too much authority. Even with friendly user-authored
apps, app HTML is agent-authored code and may later be imported from another
user. If it runs as a normal same-origin page, it can try to call unrelated
Omnideck APIs and may be able to set the same XSRF headers as trusted UI.

The app should get one intended capability: invoke public app callables for its
own active app version.

## Frame Sandbox

V1 decision: use an opaque sandbox origin.

Default v1 iframe policy:

```html
<iframe sandbox="allow-scripts"></iframe>
```

This uses long-standing iframe sandbox behavior rather than newer browser
isolation features. It should work across the modern browser target while
keeping the containment model simple enough to test.

What this does:

- `sandbox` puts the app frame in a restricted browser context instead of
  treating it like normal Omnideck UI.
- `allow-scripts` gives the app enough browser capability to run its JavaScript
  UI.
- Omitting `allow-same-origin` gives the frame an opaque origin, so app JS
  cannot act as same-origin Omnideck shell code.
- Omitting navigation, popup, form, and download permissions keeps v1 app output
  and external work behind the parent bridge and backend core callables.

Do not include by default:

```text
allow-same-origin
allow-top-navigation
allow-popups
allow-forms
allow-downloads
```

`allow-scripts` lets the app run its UI. Omitting `allow-same-origin` gives the
frame an opaque origin, which prevents it from acting as trusted Omnideck UI.

An opaque origin means the app frame does not share browser origin authority
with anything, even if its files are served by Omnideck. It cannot use Omnideck
cookies, local storage, same-origin fetch authority, or XSRF assumptions as if it
were trusted shell UI. The app gets power through the parent bridge instead.

Downloads, forms, popups, and top navigation are out of scope for v1. Add them
only when a concrete workflow requires them.

Alternatives considered and rejected for v1:

- Same-origin app HTML. Rejected because app JS could try to call unrelated
  Omnideck APIs with the user's browser authority.
- Unsandboxed iframe on the Omnideck origin. Rejected for the same reason as
  same-origin app HTML, with less visual integration benefit.
- `sandbox="allow-scripts allow-same-origin"` on the Omnideck origin. Rejected
  because the combination lets scripted app content regain same-origin authority.
- Dedicated app origin, such as `apps.omnideck.local`, with
  `allow-same-origin`. Plausible later if app frontends need normal browser
  origin behavior, persistent browser storage, service workers, or richer asset
  loading. Rejected for v1 because it is more operationally complex and still
  needs a bridge, CSP, and review model.
- Separate app origin without iframe sandboxing. Rejected because it gives app
  code a larger browser surface than v1 requires.
- Browser-native downloads/forms/popups. Deferred until a real file or OAuth
  workflow requires them; v1 should route work through app callables and core
  callables.

## Parent Bridge

The bridge is trusted Omnideck shell code. It is the only component that can use
the user's session/XSRF authority to call the app router.

Responsibilities:

- create the sandboxed frame,
- obtain the server-minted per-frame app capability token and hold it in trusted
  shell state,
- bootstrap the tiny app SDK without giving the frame authority,
- bind the frame instance to one app id, version or draft id, and allowed route
  namespace,
- verify messages come from the expected frame and active binding,
- validate callable names are simple public route names,
- forward invoke requests to the app router,
- attach required XSRF/session headers and the frame token,
- return structured results/errors to the frame,
- surface `call_id` for debugging.

The bridge does not expose a generic fetch proxy. It exposes named operations.

The app id in an invoke URL is not trusted input from the frame. The parent
bridge owns the app binding established when it created the frame. App JS sends
only an operation name such as `backup_project`; the bridge resolves that
operation against the bound app id/version or draft id. If a frame tries to
include another app id, invoke another app's route namespace, or reuse a stale
binding after the shell navigates, the bridge rejects the message before calling
the app router. This is app-to-app authorization and is separate from the XSRF
header guard.

The server repeats that authorization check with the per-frame app capability
token. If a bridge bug forwards the wrong `app_id`, or if any app code reaches
the invoke route through an unexpected path, the router still rejects the request
because the token does not match the target app/version/frame binding.

The frame token is minted by the server when the shell opens or
refreshes an app frame. It is short-lived, bound to the current user/session,
app id, app version or draft id, frame id, and route namespace, and expires when
the frame is destroyed. Navigation to another app, saving a draft as a new
version, or switching active versions requires the shell to request a new frame
binding and discard the old token.

Suggested binding route:

```text
POST /api/apps/{app_id}/frames
```

The trusted shell calls this route with the target saved version or draft id.
The server returns `frame_id`, the frame document URL, and the frame token
token for the parent bridge to keep in memory. The token is never written into
the app frame document or exposed to the SDK.

## SDK And Frame Bootstrap

With `allow-same-origin` omitted, the parent shell cannot script into the app
frame after it loads. Do not depend on post-load DOM injection.

V1 bootstrap:

1. Omnideck serves a parent-controlled frame document for the selected app
   version or draft.
2. That document includes the inert app SDK script from an Omnideck-owned,
   versioned SDK asset path.
3. The document loads the app's bundled entrypoint from the manifest.
4. The parent creates a `MessageChannel` and sends one port to the frame with a
   random bootstrap nonce.
5. The SDK binds to that port and exposes `window.omnideck`.

The SDK carries no authority. It contains no session cookies, XSRF secret,
integration tokens, app capability token, or storage credentials. It can only
send typed messages over the parent-provided port. The parent bridge decides
which messages become app-router requests.

The app bundle may include the SDK script tag directly, or the serving layer may
wrap the app entrypoint in the parent-controlled frame document. In both cases,
the app code gets an SDK API, not an authority-bearing token.

## App SDK

Tiny v1 SDK:

```ts
type InvokeResponse<T> =
  | { ok: true; call_id: string; result: T; effects?: EffectSummary[] }
  | { ok: false; call_id?: string; error: AppInvokeError };

interface OmnideckAppSDK {
  invoke<T = unknown>(route: string, args?: Record<string, unknown>): Promise<InvokeResponse<T>>;
  getAppInfo(): Promise<AppInfo>;
}
```

Runtime shape:

```js
window.omnideck.invoke("backup_project", {
  include_github_snapshot: true,
  upload_to_drive: true
});
```

`invoke` sends a message to the parent bridge:

```json
{
  "type": "omnideck.invoke",
  "request_id": "req_123",
  "route": "backup_project",
  "args": {
    "upload_to_drive": true
  }
}
```

The bridge responds:

```json
{
  "type": "omnideck.invoke.result",
  "request_id": "req_123",
  "response": {
    "ok": true,
    "call_id": "call_abc123",
    "result": {}
  }
}
```

No v1 SDK methods for:

- arbitrary HTTP/fetch,
- reading settings,
- listing integrations,
- reading files,
- uploading user files,
- downloading app-created artifacts,
- cross-app communication.

## Serving App Frontends

The frontend runtime serves the active saved app version through a parent-owned
frame route, for example:

```text
GET /api/apps/{app_id}/frame/{frame_id}/
```

Draft preview uses the same serving model with an explicit draft route:

```text
GET /api/apps/{app_id}/drafts/{draft_id}/frame/{frame_id}/
```

The trusted shell obtains the draft preview `frame_id`, frame URL, and
server-minted frame token from the same binding flow as saved apps,
using `POST /api/apps/{app_id}/frames` with a `draft_id` instead of a saved
version id. The parent bridge keeps the token in shell state; the draft frame
and SDK never receive it.

`POST /api/apps/{app_id}/frames` checks the feature flags before minting a frame
token. Saved app frames require `ai_workbench.runtime_enabled`; draft preview
frames require both `ai_workbench.builder_enabled` and
`ai_workbench.runtime_enabled`.

That route resolves files from:

```text
{settings.home_dir}/apps/{app_id}/versions/{version}/frontend/
```

Serving rules:

- serve only files listed in the app version manifest,
- verify the requested path stays under `frontend/`,
- set content types from manifest or safe detection,
- do not execute server-side code from the frontend bundle,
- treat saved version files as read-only,
- do not expose host paths in HTML, JS config, errors, or source maps.
- set a CSP for the frame document and app assets,
- bind `frame_id` to the server-side app capability token held by the parent
  bridge.

The saved app iframe should know only:

```json
{
  "app_id": "app_project_backlog",
  "title": "Project Backlog",
  "version": "3"
}
```

The app id and version are display/context data for the frontend. They are not
trusted for storage or authorization. The app router resolves app context
server-side.

## Invoke Flow

```text
app JS
  -> window.omnideck.invoke("list_backlog", args)
  -> MessageChannel message to parent bridge
  -> parent validates source, frame binding, and callable name
  -> parent POSTs /api/apps/{app_id}/invoke/list_backlog with frame token
  -> app router validates frame token against app_id/version/frame
  -> app router resolves active version and public callable
  -> callable runtime executes backend app callable
  -> app router returns structured envelope
  -> parent bridge returns result to frame
```

The app frame never receives credentials, integration tokens, broker sockets, or
host file paths.

## XSRF

The app frame should not directly attach XSRF/session authority to Omnideck API
requests. The trusted parent bridge owns that authority.

For same-origin development routes, the app invoke API still requires the
existing XSRF guard, such as:

```text
X-Requested-With: XMLHttpRequest
```

The parent bridge attaches that header. The sandboxed frame cannot use the
bridge as a generic header-setting proxy; it can only request app callable
invocation.

The server should still harden mutating routes consistently, including the
current `PATCH` gap noted in the overview.

## CSP

Start with a tight CSP for app frames:

```text
default-src 'none';
script-src 'nonce-{frame_nonce}';
style-src 'nonce-{frame_nonce}';
img-src https://{omnideck_origin} data: https://{web_allowlist_hosts};
font-src https://{omnideck_origin} data:;
connect-src 'none';
media-src https://{omnideck_origin} https://{web_allowlist_hosts};
frame-ancestors 'self';
base-uri 'none';
form-action 'none';
```

The policy is defense in depth on top of the iframe sandbox. The iframe decides
what browser capabilities the frame has; CSP decides what sources the frame may
load from and connect to if app code tries anyway.

Because v1 uses opaque sandbox origin, avoid relying on ambiguous `'self'`
semantics for route-served app assets. The parent-controlled frame document
should use nonces or hashes for SDK/app scripts and styles, and explicit
Omnideck asset origins for images, fonts, and media. Do not solve browser
differences by loosening the policy to broad network, remote script, or
same-origin app authority.

`https://{web_allowlist_hosts}` means exact hosts from the saved app manifest's
user-approved `web_allowlist`, rendered as individual CSP sources such as
`https://status.example.com`. It is omitted when the app has no approved public
web hosts or when `ai_workbench.public_fetch_enabled` is off. This is the same
allowlist used by `omnideck.http.fetch@1`, but CSP does not grant browser fetch
authority.

Policy intent:

- `default-src 'none'` denies every fetch/load type unless this policy opens it
  explicitly.
- `script-src 'nonce-{frame_nonce}'` allows only scripts the parent-controlled
  frame document explicitly emits for the SDK and bundled app entrypoint.
- `style-src 'nonce-{frame_nonce}'` allows only bundled or generated styles that
  the serving layer explicitly tags for this frame.
- `img-src https://{omnideck_origin} data: https://{web_allowlist_hosts}` allows
  bundled images from explicit Omnideck app asset routes, small embedded data
  images, and image loads from user-approved public web hosts, without letting
  apps beacon to arbitrary remote image hosts.
- `font-src https://{omnideck_origin} data:` allows bundled fonts from explicit
  Omnideck app asset routes and embedded font assets.
- `connect-src 'none'` prevents browser-side fetch/WebSocket/EventSource calls.
  App network work must go through backend app callables and core callables,
  including `omnideck.http.fetch@1` for approved public no-auth hosts.
- `media-src https://{omnideck_origin} https://{web_allowlist_hosts}` allows
  bundled media from explicit Omnideck app asset routes and media loads from
  user-approved public web hosts.
- `frame-ancestors 'self'` prevents app frontend files from being framed by
  outside sites.
- `base-uri 'none'` prevents a malicious or broken `<base>` tag from rewriting
  relative URL behavior.
- `form-action 'none'` prevents form submission as a side channel.

External display assets use the manifest-declared `web_allowlist` above. If a
later app type needs browser-side API calls, add a separate reviewed capability.
Do not allow broad network access by default, and do not repurpose
`web_allowlist` to widen `connect-src`.

Alternatives considered and rejected for v1:

- No CSP because the frame is sandboxed. Rejected because CSP catches mistakes in
  serving, bundling, and future sandbox changes.
- Broad `connect-src` or generic browser fetch proxy. Rejected because it moves
  network permission into app JS instead of the callable/broker path.
- Remote CDN scripts/styles by default. Rejected because imported apps would
  execute code outside the reviewed app bundle.
- Inline scripts with `'unsafe-inline'`. Rejected for v1 because the app bundle
  can be built with normal script files; inline script can be reconsidered only
  with nonces or hashes.
- Fully hashed CSP for all scripts and styles. Safer, but deferred because it
  requires more build pipeline machinery. The open v1 question is whether styles
  should move there immediately.
- Dedicated app origin CSP. Plausible later if v1's opaque sandbox blocks
  important app frontend capabilities. Rejected for v1 because the app should
  not need normal browser-origin behavior to invoke backend app callables.
- Newer browser isolation primitives, such as credentialless iframes or
  cross-origin isolation. Rejected for v1 because they narrow compatibility and
  do not replace the need for the parent bridge.

## Design Tokens

V1 app-builder and app-run shell UI should use the existing Omnideck design token
contract rather than app-specific palettes. The shell owns trusted chrome, app
library, import review, run details, and agent-debug surfaces, so those views use
the same light/dark theme variables as the rest of Omnideck: canvas, surface,
elevated surface, text levels, borders, accent/success/warning/danger states,
radius, spacing, and the local/system font stacks.

App-authored frontend content may render its own UI inside the sandboxed frame,
but the trusted shell should not import arbitrary app CSS into Omnideck chrome.
If v1 exposes theme values to app frames, expose them as inert data or generated
CSS variables in the parent-controlled frame document. Do not give the app frame
authority to mutate shell-level tokens or load remote theme assets.

## Preview Mode

Draft preview uses the same containment model as saved apps:

```text
draft frontend -> sandboxed frame -> parent bridge -> preview invoke route
```

Preview may point at a draft app version and live local callable refs, but it
should not relax browser isolation. The difference is which app bundle/callable
registry view the backend uses, not what the app frame can access.

The preview UI should clearly label draft mode so the user knows they are
testing an editable app, not running a saved version.

## Imported App Risk

The primary v1 use case is user-built apps, but import/export exists. Imported
apps contain code. Treat them as untrusted even when the bundle hashes validate.

Before enabling an imported app, show a review summary from the manifest:

```text
This app contains code.
Only import apps from sources you trust.

This app may:
- read and write app-local storage
- make read and write requests through connected HTTP/API integrations
- upload files through connected Drive integrations
```

The user should explicitly choose to install/enable the app. This is a risk
acceptance step, not a claim that the imported app is safe.

## App Identity And Chrome

The Omnideck shell owns app chrome around the frame:

- app title,
- active version,
- draft/saved/imported status,
- review/effects summary access,
- disable/delete/edit controls,
- "debug with agent" affordance when an action fails.

The app frame should not be able to hide or impersonate this shell chrome. Avoid
full-screen app content in v1 unless the shell still keeps a trusted escape and
identity surface.

## Errors And Debugging

The bridge returns the app router's structured envelope unchanged except for any
transport-specific wrapping.

On errors, the app frame can render the message, but the trusted shell should
also be able to surface:

```text
call_id
app_id
app_version
public callable name
```

The "debug with agent" action belongs to the shell, not the untrusted app frame.
It can hand the `call_id` to agent tooling for callable-run inspection.

## Future Extensions

The v1 bridge intentionally excludes file exchange. If requirements appear,
extend with scoped handles:

- user-selected input files,
- app-created downloadable artifacts,
- notifications,
- shared UI components,
- app-to-agent debug actions.

Do not add future file exchange as raw paths or broad artifact catalog access.
Use explicit handles scoped to one app action.

## Open Decisions

- Whether draft preview needs a separate bridge namespace from saved app run
  mode.
- Whether the shell should display sanitized effect summaries inline after every
  action or only on demand.
- Exact imported-app warning copy and install/enable flow.
