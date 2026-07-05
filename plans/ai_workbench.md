# Making Omnideck a true AI workbench

> Status: high-level draft, for discussion. Comment inline. We drill into
> the pieces once the shape is agreed.

Apps you return to, backed by the backend, built by the agent, assembled from
custom tools and the integrations the agent already has.

---

## 1. The core idea

The integration tools are already a hand-built SDK. Generalize how they are
called, let the agent extend them, and let a frontend call them.

Today each integration tool, such as `send_email`, is one function doing two
jobs. It is the programmatic caller that builds RPC args and calls
`broker_client.call(...)`. It is also the agent-facing tool with a docstring.

Split those two jobs. Underneath sits a lower-level programmatic function. On
top sits the agent-facing tool that wraps it. The agent tools stay exactly as
the agent sees them today. The lower level is a library the rest of the system
can call without going through the agent.

From there, three things build on that library:

1. Custom tools. The agent authors these. A custom tool may wrap or orchestrate
   the integration functions, or call none of them. It is callable by the agent,
   by other custom tools, and over the API.
2. Route handlers. The agent defines these. They are the app-facing endpoints.
   They invoke custom tools and integration tools.
3. Apps. Frontend assets that call route handlers over HTTP.

One thing this design does not do: it does not surface integration permissions.
Those are defined and enforced at the supervisor and broker level. An app never
sees them and never grants them. That boundary already exists and stays where it
is.

## 2. The callable model

Three kinds of callable thing, and who can call each.

| Callable | Agent calls it | Custom tools call it | Apps call it over HTTP |
|---|---|---|---|
| Integration tools (the SDK) | yes, as an agent tool | yes, the lower-level function | via a route handler |
| Custom tools (agent-authored) | yes, as an agent tool | yes | via a route handler, or a direct invoke API |
| Route handlers (agent-defined) | no, they call the others | n/a | yes, this is their whole job |

There are two ways to invoke these that are not the agent. Over HTTP, which is
how apps reach route handlers. And programmatically, which is one custom tool
calling another or calling an integration function.

The app path, top to bottom:

```
  ┌─────────────────────────────────────────────────────┐
  │ APP   (frontend static asset — maybe an artifact)    │
  └───────────────────────────┬─────────────────────────┘
                              │  HTTP, XSRF-guarded
                              ▼
  ┌─────────────────────────────────────────────────────┐
  │ ROUTE HANDLER   (agent-defined, app-facing)          │
  └───────┬─────────────────────────────────┬───────────┘
          │ invokes                          │ invokes
          ▼                                  ▼
  ┌────────────────┐                ┌─────────────────────┐
  │ CUSTOM TOOLS   │ ─ may call ──▶ │ INTEGRATION TOOLS    │
  │ (agent-        │ ◀─ may call ─  │ (hand-built SDK:     │
  │  authored)     │                │  lower-level fn +    │
  └───────┬────────┘                │  agent-tool wrapper) │
          │ may call other          └──────────┬──────────┘
          └── custom tools                     │
                                               ▼
             broker_client → supervisor → broker → upstream
             integration permissions enforced HERE, never surfaced up
```

The agent, separately, calls integration tools and custom tools directly as its
own tools. That does not change.

## 3. Integration tools as a hand-built SDK

Split each integration tool into a lower-level function and an agent-tool wrapper
over it. The agent-facing surface is untouched. The lower-level function is what
custom tools and route handlers call. This is a refactor of what already exists,
not a new subsystem. Do not build a registry with its own permission model on top
of it. The permission model lives in the broker.

## 4. Custom tools

Custom tools are the unit the agent extends the system with. Today they are
agent-authored shell or Python scripts run in-process, and they cannot call
another tool or an integration. Rework them into real callable units.

A custom tool:

- is authored by the agent,
- is callable by the agent as a tool, as it is today,
- is callable by other custom tools, programmatically,
- is callable over the API,
- may wrap or orchestrate integration functions and other custom tools, or call
  nothing external and just run its own logic.

The agent's tool surface stays small. It keeps discovering and running custom
tools through a stable path rather than seeing each one as its own schema. What
changes is that a custom tool can now reach the integration SDK and other custom
tools, and can be invoked over HTTP.

The execution model is an open decision. In-process is simplest. A subprocess
per tool, behind a small RPC, mirrors how the broker already runs semi-trusted
code with a clean boundary. This runs agent-authored code that can now reach
integrations, so isolation matters more than it did.

## 5. Route handlers

Route handlers are the foundation of apps. The agent defines a route handler as
the endpoint an app calls. A handler invokes custom tools and integration tools
and returns a result. It is the seam between a frontend app and the backend the
agent has built.

Open question on the shape of the HTTP surface. It could be bespoke handlers the
agent writes per app. It could be a generic "invoke this custom tool" endpoint.
It is probably both: named handlers for app-specific orchestration, plus a
generic path so a custom tool is reachable without hand-writing a handler.

## 6. Apps

An app is a frontend asset that calls route handlers. Whether an app is a kind of
artifact or a separate entity is your call to make. Artifacts today are static
assets. An app could be a static asset that happens to be an app, or its own
thing that references an asset. This decision shapes the storage and the UI.

What an app needs around it:

- Pinning. Add an app to the sidebar so it is easy to retrieve and return to.
- Reversible versioning. Iterate on an app and roll back to an earlier version.
- Management. List, rename, delete.
- Provenance. Track which custom tools and route handlers each app uses, so you
  can see what is in play and what breaks if you remove a tool.

## 7. Helping the agent build

The agent needs to know what exists and needs tools to create the new things.

- Discovery. The agent can list what is available to build on: the integration
  SDK functions, existing custom tools, existing route handlers, and existing
  apps.
- Creation tools. The agent has tools to create a custom tool, define a route
  handler, and create or update an app.
- A skill. A skill teaches the agent how these pieces fit together and how to
  assemble an app from them, the way skills already package how-to for the agent.

## 8. XSRF and isolation

XSRF has to be handled. The current defense is a header trick: mutating requests
must carry an `X-Requested-With` header the server refuses to allow cross-origin.
Extend that guard to the route-handler API, and close the gap where `PATCH` is
currently unguarded.

App isolation is a separate, open question. App HTML is agent-authored and could
be shared and imported later, so it is not fully trusted. Options range from
same-origin with the existing header guard, to a sandboxed frame on an isolated
origin that talks to the parent shell rather than the API directly. This is about
containing untrusted frontend code. It is not about integration permissions,
which stay at the broker.

## 9. Open decisions

- Name for the apps feature. Being workshopped.
- Are apps a kind of artifact, or a separate entity.
- The HTTP surface: bespoke route handlers, a generic invoke API, or both.
- Custom-tool execution model: in-process or subprocess-per-tool.
- App isolation: same-origin with the header guard, or an isolated sandboxed
  frame.
- How much of the custom tools and route handlers to expose to the user in the UI
  versus keep as agent-managed internals.
- The versioning model for reversible iteration.

## 10. Phasing

A rough order, to be revised as decisions land.

| Phase | Contents | What it proves |
|---|---|---|
| 1 | Split the integration SDK into lower-level functions plus the agent-tool wrappers. Add discovery so the agent can list what exists. | The library layer, with no user-visible change. |
| 2 | Rework custom tools into callable units that can reach the SDK and each other. Add the programmatic and API invoke paths. | The agent can build reusable backend logic. |
| 3 | Route handlers plus a first app that calls one, pinned to the sidebar. XSRF handled. | The frontend can invoke the backend the agent built. |
| 4 | Versioning, management, provenance tracking, and the build skill and creation tools. | Apps are iterable, manageable, and agent-buildable end to end. |

Naming note. The computron to omnideck rename is in flight, with omnideck#110
before cli#8. Build with omnideck naming from the start, and land phase 1 after
#110 settles so the new code does not add churn to the rename.
