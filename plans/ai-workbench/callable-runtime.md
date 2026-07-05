# Callable Runtime

> Detailed design for how Omnideck callables are packaged, stored, exposed to
> the agent, and invoked by apps and other callables.

## Core Model

A callable is versioned backend code with a manifest, input and output schemas,
dependencies, effects metadata, and a scope. Core, local, and app callables use
the same package format but live in different roots.

Scopes:

| Scope | Owner | Shared directly? | Agent callable? | App frontend callable? |
|---|---|---:|---:|---:|
| Core callable | Omnideck | ships with Omnideck | optional | only through app callables |
| Local callable | user install | no, private to this install | optional | only if vendored into an app |
| App callable | app version | only as part of the app bundle | no | yes, if public |

Programmatic invocation is inherent to callables. A callable can invoke another
callable when it declares that callable as a dependency and the caller's scope is
allowed to resolve it.

Agent exposure is separate. Core and local callables may declare an
`agent_binding`, which gives the LLM an agent-friendly name, description,
argument guidance, and result format. App callables never have agent bindings.
An agent binding can be exposed in `direct` mode, where the callable becomes its
own LLM tool schema, or `catalog` mode, where the agent discovers it through the
callable catalog and invokes it through a stable generic runner. Local callables
default to catalog mode to avoid bloating the model's tool surface.

App exposure is also separate. App callables declare `app_visibility` as
`public` or `private`. The built-in app router can invoke public app callables
only. Private app callables can only be invoked by other app callables in the
same app version.

App callables are not LLM-bindable. The agent can inspect, edit, and test them
when it is working on that app, but they do not become reusable agent tools. If
app logic should be reusable elsewhere, the agent extracts it into a local
callable. A later app version can vendor a copy of that local callable.

## Registry And Storage

One callable registry resolves ids to executable definitions. It is a runtime
view over three backing stores:

1. Core catalog. Built into the Omnideck source tree and registered at startup.
2. Local callable store. User-created callables persisted in Omnideck state.
3. App bundle manifest. App-scoped callables and vendored dependencies loaded
   from one app version.

The registry is not a permission system. It answers:

- what callable exists,
- where its implementation lives,
- which version is selected,
- what schemas and effects it declares,
- which other callables it depends on,
- which agent binding or app visibility it exposes.

All callable scopes use the same package format: a manifest plus implementation
files. The registry loads the same shape from different roots: core packages
from the repo, local packages from user state, and app packages from app bundles.

## Manifest Shape

Local and app callables should persist explicit JSON schemas in their manifests
so they can be validated, reviewed, bundled, and invoked without importing
arbitrary code first. Core callable schemas can be generated from typed Python
functions where that is clean, reusing the existing callable-to-tool-schema
machinery.

Minimal local callable manifest:

```json
{
  "id": "local.normalize_bank_csv",
  "version": "2",
  "scope": "local",
  "title": "Normalize bank CSV",
  "description": "Clean bank CSV exports into a standard transaction table.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": { "type": "string" }
    },
    "required": ["path"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "normalized_path": { "type": "string" }
    },
    "required": ["normalized_path"]
  },
  "effects": [
    { "kind": "file.write", "summary": "Writes a normalized CSV file" }
  ],
  "dependencies": [
    "omnideck.file.read@1",
    "omnideck.file.write@1"
  ],
  "agent_binding": {
    "enabled": true,
    "exposure": "catalog",
    "name": "normalize_bank_csv",
    "description": "Normalize a bank CSV export.",
    "argument_descriptions": {
      "path": "Path to the source CSV file."
    },
    "usage_notes": [
      "Use this when the user provides a raw bank export.",
      "The result is a new normalized CSV file path."
    ],
    "result_format": "json"
  },
  "implementation": {
    "kind": "python_script",
    "path": "implementation.py"
  }
}
```

Core callable package:

```text
callables/core/omnideck.email.send/
  manifest.json
```

```json
{
  "id": "omnideck.email.send",
  "version": "1",
  "scope": "core",
  "title": "Send email",
  "input_schema": {
    "type": "object",
    "properties": {
      "integration_id": { "type": "string" },
      "to": { "type": "array", "items": { "type": "string" } },
      "subject": { "type": "string" },
      "body": { "type": "string" }
    },
    "required": ["integration_id", "to", "subject", "body"]
  },
  "implementation": {
    "kind": "python_import",
    "target": "tools.integrations.send_email:send_email"
  },
  "effects": [
    {
      "kind": "email.write",
      "summary": "Sends email through a connected email integration"
    }
  ],
  "agent_binding": {
    "enabled": true,
    "exposure": "direct",
    "name": "send_email",
    "description": "Send an email through a connected email integration.",
    "argument_descriptions": {
      "integration_id": "Which connected email integration to send through.",
      "to": "Recipient email addresses.",
      "subject": "Subject line.",
      "body": "Plain-text email body."
    },
    "runtime_hints": {
      "integration_id": {
        "source": "connected_integrations",
        "capability": "email",
        "access": "read_write"
      }
    },
    "result_format": "text",
    "builder": "tools.integrations.send_email:build_send_email_tool"
  }
}
```

App callable manifest:

```json
{
  "id": "app.submit_invoice",
  "version": "1",
  "scope": "app",
  "app_visibility": "public",
  "title": "Submit invoice",
  "input_schema": {
    "type": "object",
    "properties": {
      "invoice_path": { "type": "string" }
    },
    "required": ["invoice_path"]
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "draft_id": { "type": "string" }
    },
    "required": ["draft_id"]
  },
  "implementation": {
    "kind": "python_script",
    "path": "implementation.py"
  },
  "dependencies": [
    "app.parse_invoice_pdf@1",
    "vendor.local.normalize_vendor@1",
    "omnideck.email.create_draft@1"
  ]
}
```

App callables never have `agent_binding`; they use `app_visibility` to decide
whether the app router may invoke them.

## Storage Roots

Core callables use the same package format but are code-owned, not
user-state-owned. Store their packages in the repo. The implementation can stay
where it is today by using a Python import target:

```text
callables/core/omnideck.email.send/
  manifest.json
```

Local callables should be backend-owned durable state under `settings.home_dir`,
not loose ad hoc scripts. The agent edits them through creation/edit/test tools;
the runtime snapshots each saved version:

```text
{settings.home_dir}/callables/
  local/
    index.json
    normalize_bank_csv/
      current.json
      versions/
        1/
          manifest.json
          implementation.py
        2/
          manifest.json
          implementation.py
```

`index.json` is for listing and lookup. `current.json` points at the active local
version. Versions are immutable once saved. Updating a local callable creates a
new version and moves the current pointer. Draft apps may reference the current
version while the agent iterates. Versioned apps vendor a copy of the selected
version into the app bundle.

App callables live only inside an app version:

```text
{settings.home_dir}/apps/{app_id}/versions/{version}/
  manifest.json
  frontend/
  callables/
    submit_invoice/
      manifest.json
      implementation.py
  vendor/
    local.normalize_vendor/
      manifest.json
      implementation.py
```

The app bundle manifest is the source of truth for `app_visibility` and for
which vendored callables are available to that app version. A saved app never
reaches back into the live local callable store.

## Invocation Model

Invocation goes through one internal service, not through LLM tools:

```text
invoke_callable(ref, args, context) -> result
```

`ref` is a callable id plus version selector. `args` is JSON-shaped input.
`context` carries who is calling and what scope is active:

```text
caller: agent | local_callable | app_callable | app_router
app_id: optional
app_version: optional
call_stack: for recursion limits and diagnostics
```

The invoker does the same work for every caller:

1. Resolve the callable from the allowed stores for this context.
2. Verify the caller is allowed to invoke that scope.
3. Validate args against the input schema.
4. Execute the implementation.
5. Validate the result against the output schema.
6. Return a structured result or structured error.

Allowed paths:

| Caller | May invoke |
|---|---|
| Agent tool binding | bound core or local callable only |
| Local callable | core callables and other local callables |
| Draft app callable | app draft callables, core callables, and live local callables |
| Versioned app callable | bundled app callables, vendored callables, and core callables |
| App router | public app callables in the active app version only |

The important containment rule: app router requests never name core, local, or
vendored callables directly. They name public app callables. Those app callables
perform any orchestration by invoking private app callables, vendored callables,
and core callables programmatically.

Core callables can be direct Python async functions. Local and app callables
should use a small implementation contract that can run either in-process or in a
subprocess:

```text
input:  JSON args on stdin or RPC frame
output: JSON result or structured error
```

If subprocess isolation is chosen, the callable receives an Omnideck invocation
SDK endpoint in its environment. That SDK lets it call allowed dependencies
without seeing credentials:

```python
result = await omnideck.invoke("omnideck.email.create_draft@1", {...})
```

The SDK call routes back through `invoke_callable(...)`, so dependency checks,
schema validation, call-stack limits, events, and broker enforcement stay in one
place.

## Names, Manifests, And Hashes

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
      "app_visibility": "public",
      "path": "callables/submit_invoice.py",
      "sha256": "..."
    },
    "parse_invoice_pdf": {
      "app_visibility": "private",
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
