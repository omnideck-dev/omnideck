# Making Omnideck a true AI workbench

> Status: high-level draft, for discussion. Comment inline. We drill into
> the pieces once the shape is agreed.

Apps you return to, backed by backend logic the agent can build, bundled with
the callables they need, and connected to the integrations the user already
granted to Omnideck.

---

## 1. The core idea

The backend unit is a callable: versioned code with a manifest, input and output
schemas, dependencies, and metadata about what it does. Everything else is a
binding over callables.

Today each integration tool, such as `send_email`, is one function doing two
jobs. It is the programmatic caller that builds RPC args and calls
`broker_client.call(...)`. It is also the agent-facing tool with a docstring.
Split those two jobs. Underneath sits a core callable. On top sits the
agent-facing tool binding that keeps the LLM-facing surface exactly as it is.

From there:

1. Core callables are built into Omnideck. Some wrap integrations. Others may
   provide app storage, artifact access, HTTP, file operations, or other first
   party capabilities.
2. Local callables are reusable automations the agent creates for this user's
   install. They are private by default and may have an agent-tool binding.
3. App callables are bundled into one app version. Public app callables can be
   invoked by that app's frontend through the built-in app router. Private app
   callables can only be invoked by other callables inside the same app.

Apps do not define bespoke backend routes. The app runtime provides a generic
invoke route for public app callables:

```text
POST /api/apps/{app_id}/invoke/{callable_name}
```

If an app needs orchestration, that orchestration lives in an app callable. The
router stays generic.

One thing this design does not do: it does not reimplement integration
permissions. Those are defined and enforced at the supervisor and broker level.
An app never sees credentials and never grants Gmail or Drive access. The app
router only decides whether the app frontend may invoke a public app callable.
The callable still fails if the broker denies the integration operation.

## 2. Callable model

A callable has:

- a stable id or namespace,
- a version,
- input and output schemas,
- an implementation,
- a manifest,
- dependencies,
- optional hashes for bundled files,
- a scope,
- optional bindings.

Scopes:

| Scope | Owner | Shared directly? | Agent callable? | App frontend callable? |
|---|---|---:|---:|---:|
| Core callable | Omnideck | ships with Omnideck | optional | only through app callables |
| Local callable | user install | no, private to this install | optional | only if vendored into an app |
| App callable | app version | only as part of the app bundle | no | yes, if public |

Bindings:

- Programmatic binding: one callable invokes another.
- Agent-tool binding: the LLM gets an agent-friendly name, description,
  arguments, and result format for a core or local callable.
- App-public binding: the built-in app router can invoke a public app callable.

App callables are not LLM-bindable. The agent can inspect, edit, and test them
when it is working on that app, but they do not become reusable agent tools. If
app logic should be reusable elsewhere, the agent extracts it into a local
callable. A later app version can vendor a copy of that local callable.

## 3. Names, manifests, and hashes

Every callable needs a unique identity under the hood, even if regular users see
friendly names. Use namespaces, not bare names:

```text
omnideck.email.send@1
omnideck.app.storage.get@1
local.normalize_bank_csv@1.0.0
app.submit_invoice@1.0.0
```

Core ids are stable API families owned by Omnideck. Local ids are private to the
install. App ids are meaningful only inside an app bundle. If standalone
callable sharing is added later, it can introduce community or publisher
namespaces, but that is not needed for the first version.

Each packaged app version has a manifest. The manifest is both the reviewable
contract and the bundled-content inventory. Avoid a package-manager-style
lockfile for v1. Since app versions vendor the code they need, hashes can live
directly in the manifest:

```json
{
  "id": "app.invoice_dashboard",
  "version": "3",
  "requires": {
    "omnideck_core": ">=1"
  },
  "core_dependencies": [
    "omnideck.email.create_draft@1",
    "omnideck.app.storage@1"
  ],
  "callables": {
    "submit_invoice": {
      "visibility": "public",
      "path": "callables/submit_invoice.py",
      "sha256": "..."
    },
    "parse_invoice_pdf": {
      "visibility": "private",
      "path": "callables/parse_invoice_pdf.py",
      "sha256": "..."
    }
  },
  "vendored_callables": {
    "local.normalize_vendor": {
      "version": "1.0.0",
      "path": "vendor/local.normalize_vendor/",
      "sha256": "..."
    }
  }
}
```

The hash is tamper evidence and supports exact rollback. It does not mean the
code is trusted. Review, isolation, and broker enforcement still matter.

## 4. Apps and bundles

An app is a versioned bundle, not a live pointer to an artifact file. Promoting
an artifact to an app copies it into app-owned storage and creates version 1.
The artifact remains provenance. The app runtime serves the app bundle.

Recommended storage shape:

```text
apps/{app_id}/versions/{version}/
  manifest.json
  frontend/
  callables/
  vendor/
```

Draft apps may reference local callables by reference during development. That
keeps iteration fast: if the agent improves a local callable, the draft can use
the improved version immediately.

Versioned apps vendor everything they need except Omnideck core callables. When
the user pins, saves, or exports an app, Omnideck snapshots the frontend, app
callables, and any local callable dependencies into the app version. Running the
saved app uses the bundled copies, so it does not silently change when a local
callable changes later.

Import/export stays simple: an exported app contains its frontend and all
non-core callable code it needs. The importing install only needs a compatible
Omnideck core API and the user's existing integration grants.

## 5. Local callables

Local callables replace the old "custom tools" concept. They are reusable
automations the agent creates for this user's install. They are private by
default, not directly shared, and may have an agent-tool binding so the LLM can
use them later through a stable discover/run path.

Examples:

```text
normalize_bank_csv
summarize_meeting_notes
clean_contact_list
resize_images_for_listing
```

Local callables can invoke core callables and other local callables. App callables
can invoke local callables while the app is a draft. Once the app is versioned,
those local callable dependencies are copied into the app bundle.

Standalone sharing of local callables is out of scope for v1. If users later
want to share reusable automations independently of apps, add "export local
callable as library" as a separate feature. Do not make app sharing depend on a
package manager.

The execution model is still an open decision. In-process is simplest. A
subprocess per callable, behind a small RPC, mirrors how the broker already runs
semi-trusted code with a clean boundary. This code is agent-authored and may
reach integrations through core callables, so isolation matters more than it did
for today's shell-style custom tools.

## 6. Core callables and integrations

Split each integration tool into a core callable plus the existing agent-tool
binding. The LLM-facing tool shape stays unchanged. The core callable is what
local callables and app callables invoke programmatically.

Do not build a second integration permission system above the broker. Core
integration callables still call `broker_client.call(...)`, and the supervisor
and broker remain the source of truth for `Capability x Access`.

The callable manifest should still record effects in user-facing language so app
import/save review can summarize what an app may do transitively:

```text
This app may:
- create draft emails through connected email integrations
- read and write app-local storage
- read files bundled with the app
```

That summary is not a new integration grant. It is an explanation of what the
bundled app callables can trigger if the user's existing broker permissions
allow it.

## 7. App router

The app router is built into Omnideck. Apps do not define arbitrary HTTP
handlers for v1. The frontend invokes public app callables:

```text
POST /api/apps/{app_id}/invoke/{callable_name}
```

Router behavior:

1. Resolve the app and active version.
2. Confirm `callable_name` is an app-scoped callable in that version.
3. Reject it if the callable is private.
4. Validate request args against the callable input schema.
5. Invoke the bundled callable.
6. Validate and serialize the result.

Shared/core/local dependencies are not directly invokable through an app route.
They are reachable only from app callables that explicitly depend on them.

## 8. Helping the agent build

The agent needs to know what exists and needs tools to create the new things.

- Discovery. The agent can list core callables, local callables, app bundles,
  and app callables when editing a specific app.
- Creation tools. The agent has tools to create, update, test, and delete local
  callables; create and update draft apps; add app callables; and save a
  draft as a versioned app bundle.
- Extraction. The agent can extract useful app logic into a local callable, or
  vendor a local callable into an app version.
- A skill. A skill teaches the agent how these pieces fit together and how to
  assemble an app from them, the way skills already package how-to for the agent.

The user-facing language should stay simple. "Callable" is an internal design
term. The UI can describe these as reusable automations, app actions, and app
versions.

## 9. XSRF and isolation

XSRF has to be handled. The current defense is a header trick: mutating requests
must carry an `X-Requested-With` header the server refuses to allow cross-origin.
Extend that guard to the app invoke API, and close the gap where `PATCH` is
currently unguarded.

App isolation should default to a sandboxed frame, not same-origin execution.
App HTML is agent-authored and may later be imported from another user, so it is
not fully trusted. A same-origin frame can set the existing XSRF header and call
unrelated `/api/*` routes. The recommended runtime is an isolated sandboxed frame
with a CSP and a parent bridge. The open decision is opaque sandbox versus a true
second origin, not whether same-origin is enough.

This is about containing untrusted frontend code. It is not about integration
permissions, which stay at the broker.

## 10. Next planning layers

The callable/app-bundle model is the foundation. After that shape is locked,
drill into these layers separately so the core model does not keep changing while
we work through implementation details:

- UX. Decide the user-facing language for apps, reusable automations, app
  actions, versions, save/pin/export/import, and review summaries. Avoid
  exposing internal terms like "callable" unless they prove useful.
- Core callable refactor. Decide how integration tools split into core
  callables plus agent-tool bindings, how schemas are generated, and how effects
  are described for app review.
- Local callable runtime. Decide the execution boundary, storage model,
  dependency policy, testing flow, and agent creation/editing tools.
- App router. Specify the generic invoke API, request/response envelope, schema
  validation, public/private checks, active-version resolution, and error shape.
- Frontend architecture. Decide app hosting, iframe bridge, SDK injection,
  design-token/component delivery, app manager surfaces, and artifact promotion
  flow.
- Bundle format. Specify manifest schema, hash coverage, version directories,
  vendoring rules, import/export archive format, and rollback behavior.

## 11. Open decisions

- Name for the apps feature. Being workshopped.
- Internal/external naming for "callable", "local callable", and "app callable".
- Local callable execution model: in-process or subprocess-per-callable.
- App isolation implementation: opaque sandbox or true second origin.
- How much of the local callable inventory to expose to the user versus keep as
  agent-managed internals.
- Whether standalone local-callable sharing ever exists, separate from app
  export/import.

## 12. Phasing

A rough order, to be revised as decisions land.

| Phase | Contents | What it proves |
|---|---|---|
| 1 | Split integration tools into core callables plus agent-tool bindings. Add callable manifests and discovery. | The callable layer, with no user-visible change. |
| 2 | Implement local callables with programmatic invocation, optional agent-tool bindings, and the chosen execution boundary. | The agent can build reusable backend logic. |
| 3 | Add app bundle storage, artifact promotion by copying into versioned bundles, public/private app callables, and generic app invoke. | A saved app can invoke its own bundled backend logic. |
| 4 | Add sandboxed app hosting, CSP/bridge, XSRF hardening including `PATCH`, and import/export review summaries. | Apps are contained and portable. |
| 5 | Add management UI, rollback, provenance views, extraction/vendoring flows, and the build skill. | Apps are iterable, manageable, and agent-buildable end to end. |

Naming note. The computron to omnideck rename is in flight, with omnideck#110
before cli#8. Build with omnideck naming from the start, and land phase 1 after
#110 settles so the new code does not add churn to the rename.
