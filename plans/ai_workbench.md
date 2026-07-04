# Making Omnideck a true AI workbench

> Status: high-level draft, for discussion. Comment inline. We drill into
> individual workstreams once the shape is agreed.

Apps you return to, backed by the backend, built by the AI, isolated from each other.

---

## 1. The core idea

The layering we want already exists in the codebase, but only for integrations. Generalize it, then build Apps on top.

Today `tools/integrations/send_email.py` is two things fused into one function. It is a deterministic caller that builds RPC args and calls `broker_client.call(...)`. It is also an LLM wrapper with a docstring. Below it, `integrations/broker_client/_call.py` is a stable, credential-isolated boundary to the broker and supervisor. That is the "LLM tools → deterministic tools → broker/supervisor" stack, half-built.

The plan does four things:

1. Split that fused layer into an explicit deterministic tier. Call each unit an "action": a typed function with a declared permission, callable from anywhere, with no LLM docstring semantics.
2. Make LLM tools thin wrappers over actions. This is the existing `build_*_tool` pattern, generalized.
3. Turn custom tools into "providers" that register new actions and can call other actions and integrations.
4. Add Apps as a first-class entity, promoted from an artifact, that calls actions through a security-isolated bridge.

One term clash to settle up front. The integrations code already uses `Capability` for email, calendar, and http. This doc uses "action" for the new deterministic tier so it does not overload that word.

## 2. What an app is, concretely

An artifact is a pointer to a file the user views once. An app is a registered, versioned entity the user returns to, docked in the nav, that can call the backend.

The difference in the data model is small, and that is the point. An artifact is an `ArtifactEntry` row pointing at an HTML file under `/home/omnideck`. An app is that same file plus a manifest: a name, an icon, a granted set of actions, an optional set of backend handlers, and a version. Promote-artifact-to-app writes the manifest and registers it. Nothing about the file has to change.

## 3. Target architecture

```
  ┌─────────────────────────────────────────────────────────────┐
  │ FRONTEND (SPA origin)                                        │
  │  left nav ── Apps folder ── App launcher                     │
  │  App host frame  (isolated origin, sandboxed, CSP-locked)    │
  │     └─ app bundle + injected Omnideck SDK ──postMessage──┐   │
  └──────────────────────────────────────────────────────────┼──┘
                                                              │
  ┌───────────────────────────────────────────────────────── ▼ ─┐
  │ APP BRIDGE   POST /api/apps/{id}/actions/{name}             │
  │   • CSRF header check    • per-app grant check             │
  │   • resolves {name} against the app's granted actions      │
  └───────────────────────────────┬────────────────────────────┘
                                  │
  ┌──────────────────────────  TIER 2  ─────────────────────────┐
  │ ACTION REGISTRY  (deterministic, typed, permission-tagged)  │
  │  built-in actions │ integration actions │ provider actions  │
  └──────┬────────────────────┬────────────────────┬────────────┘
         │ wrapped by          │ called by          │ registered by
  ┌──────▼──────────┐  ┌───────▼────────┐   ┌───────▼──────────┐
  │ TIER 1 LLM tools│  │ App backend    │   │ Providers        │
  │ (docstring)     │  │ handlers (AI)  │   │ (revamped custom │
  │                 │  │                │   │  tools)          │
  └──────┬──────────┘  └───────┬────────┘   └───────┬──────────┘
         └─────────────  all call  ─────────────────┘
                                  │
  ┌──────────────────────────  TIER 3  ─────────────────────────┐
  │ broker_client.call → supervisor (resolve) → broker → upstream│
  │  credential isolation, Capability×Access, unchanged         │
  └─────────────────────────────────────────────────────────────┘
```

The action registry is the new center of gravity. Everything above it calls it. Everything below it stays as-is.

## 4. The security model is the load-bearing decision

Everything else is mechanical. This is the part to get right. It is the XSRF concern.

Here is the problem, grounded in the current code. HTML artifacts render in an iframe with `sandbox="allow-scripts allow-same-origin"`, same-origin, with no CSP anywhere in the app. Same-origin plus `allow-same-origin` means the framed document can call every `/api/*` route. The only CSRF defense is a header trick: mutating requests must carry `X-Requested-With: XMLHttpRequest`, and the server refuses to allow that header cross-origin. A same-origin frame can set it freely.

If apps run same-origin, every app and every plain HTML artifact can call every backend endpoint. Per-app capability scoping becomes advisory, not a boundary. A prompt-injected app could read conversations and send them out. That defeats the point of granting apps specific actions.

The fix is defense in depth. Recommended shape:

1. Serve app frames from an isolated origin. Use `sandbox="allow-scripts"` without `allow-same-origin`. That gives the frame an opaque origin. It cannot read cookies or localStorage, and it cannot reach `/api/*` as same-origin. The existing CSRF header trick already blocks its cross-origin mutating calls, for free.
2. Lock the frame with a CSP. Set `default-src 'none'`, allow only the injected SDK, and set `connect-src 'none'` so the app cannot fetch arbitrary external URLs. This closes the exfiltration path that sandboxing alone leaves open.
3. Route all backend access through the parent. The app talks only to the parent shell over `postMessage`. The parent holds the app's identity and forwards allowed calls to the app bridge. The parent is the single choke point.
4. Enforce the grant server-side. The bridge endpoint checks the requested action against the app's manifest grant before dispatching. The manifest is the source of truth. The browser is never trusted to self-limit.
5. Keep the broker boundary intact. Apps never see credentials. They call actions, actions call `broker_client.call`, and the broker holds the token and enforces `Capability×Access` at verb dispatch. This is already true and stays true.

The developer-experience cost of an opaque origin is that the app cannot directly import the SPA's CSS or React components. The injected SDK solves this. The parent injects a small JS SDK and the design tokens into the frame at load. App authors write `omnideck.call('send_email', {...})` and use the provided components. They never touch `postMessage`.

Two smaller hardening items fall out. Add `PATCH` to the CSRF-guarded methods; it is currently unguarded. Add a CSP to app responses specifically; the rest of the app can stay CSP-free for now.

## 5. Workstreams

Ordered so each is usable on its own and later ones depend on earlier ones. These are shape, not implementation. We expand one at a time.

### WS1 — The action registry (deterministic tier)

One registry of typed, permission-tagged deterministic functions that LLM tools, apps, and backend handlers all call. An action is a plain function plus metadata: a stable name, a typed input, a typed output, and a permission requirement in the existing `Capability×Access` grammar, or `none` for unprivileged actions. Refactor the integration tools to sit on this: split each into an action and a thin LLM adapter. Seed the registry with built-in actions beyond integrations, such as sandboxed file read/write, artifact read, scoped key-value storage, and generic HTTP.

### WS2 — Capability discovery and introspection

The AI can read what deterministic actions exist so it can build handlers and apps against them. A machine-readable catalog over HTTP, plus an LLM tool that returns the same, so the agent discovers actions the way it already discovers custom tools.

### WS3 — Custom tools become providers

Custom tools graduate from shell scripts to backend providers that register actions and can call integrations. Keep the three meta-tool dispatch pattern so the LLM's schema surface stays constant. Change what a custom tool is: a module that registers actions, declares the permissions it needs, and can invoke other actions. Give providers a real lifecycle: register, list, enable and disable, delete, export, import. The execution model is an open decision (see below).

### WS4 — The App entity and lifecycle

Register, list, manage, deregister, delete, export, and import apps. An app store parallel to the artifacts store, with an `AppManifest` persisted as JSON. Promote-from-artifact is the primary create path. Export and import make apps shareable, with import surfacing the requested action grant for user approval before the app can run.

### WS5 — The app bridge and grants (security core)

The secured runtime path from an app frame to an action. A bridge endpoint reads the manifest, checks the requested action against the grant, validates the body against the action schema, and dispatches. The grant is enforced server-side. This is where the manifest grant becomes a real boundary rather than metadata.

### WS6 — App backend handlers

The AI writes server-side logic for an app that composes actions, for apps that need more than a single action call. Handlers are bound to one app, run under its grant, and are deregistered when the app is deleted. The AI builds them using the WS2 introspection surface.

### WS7 — Frontend: nav, launcher, promote flow, host frame

Apps are visible, launchable, and manageable, and they look like Omnideck. An Apps nav item, a launcher and manager view, a promote action in the artifact view, and the isolated, sandboxed, CSP-locked host frame that injects the SDK and brokers postMessage to the bridge.

### WS8 — Style guide and component kit for apps

Apps can match the host with low effort, without importing the SPA. Ship the existing SIGNAL design tokens as a standalone CSS file injected into every app frame. Ship a small web-component kit inside the SDK: button, input, card, list, badge, modal. Give the AI a small app style guide to read before building an app. Start with tokens plus five components; go deeper only if apps need it.

## 6. Phasing

Build it so each phase ships something usable.

| Phase | Name | Contents | What the user gets |
|---|---|---|---|
| 1 | The spine | WS1 action registry with integrations refactored onto it, plus WS2 introspection. | No user-visible change. Proves the tiering, unblocks everything. |
| 2 | Apps that read | WS4 app entity and promote-from-artifact, WS5 bridge with a read-only grant, WS6 minimal, WS7 nav and host frame. | An app can render and call read actions. First thing the user can touch. |
| 3 | Apps that do | Widen grants to write actions, WS3 providers, WS6 backend handlers. | Apps write email, mutate state, compose logic. |
| 4 | Sharing and polish | Export and import with import-time approval, WS8 component kit, app manager UI. | Shareable apps, house-styled, fully managed. |

## 7. Open decisions

Three forks change the shape. The rest is a recommendation to proceed on.

1. Origin isolation strategy. Recommend opaque-sandbox: `sandbox="allow-scripts"` without `allow-same-origin`, plus CSP, plus a postMessage bridge. Needs no second domain. The alternative is a real second origin, which is stronger against some attacks but requires the container to serve a second host and the CLI to expose it.
2. Provider and handler execution model. Recommend per-provider subprocess behind RPC, mirroring the broker model, over in-process. These run AI-authored code that can now reach integrations. Subprocess is stronger isolation the codebase already trusts, but more work.
3. Apps nav placement. Recommend a distinct Apps nav item, with promote living in the artifact view, over nesting under Artifacts.

Naming note. The computron to omnideck rename is in flight, with omnideck#110 before cli#8. Build this subsystem with omnideck naming from the start, and land Phase 1 after #110 settles so the new packages do not add churn to the rename.
