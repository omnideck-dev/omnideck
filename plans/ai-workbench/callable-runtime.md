# Callable Runtime

> Detailed design for how Omnideck callables are packaged, stored, exposed to
> the agent, and invoked by apps and other callables.

## Core Model

A callable is versioned backend code with a manifest, input and output schemas,
package dependencies, callable dependencies, effects metadata, and a scope.
Core, local, and app callables use the same package format but live in different
roots.

Scopes:

| Scope | Owner | Shared directly? | Agent callable? | App frontend callable? |
|---|---|---:|---:|---:|
| Core callable | Omnideck | ships with Omnideck | optional | only through app callables |
| Local callable | user install | no, private to this install | optional | only if vendored into an app |
| App callable | app version | only as part of the app bundle | no | yes, if public |

Programmatic invocation is inherent to callables. A callable can invoke another
callable when it declares that callable as a callable dependency and the caller's
scope is allowed to resolve it.

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
- which package dependencies it needs,
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

Manifests distinguish package dependencies from callable dependencies:

- `package_dependencies` are language/runtime packages installed into the
  callable runner environment, such as Python packages.
- `callable_dependencies` are other Omnideck callables this callable may invoke
  through the parent-managed invocation API. They are never imported or installed
  into the runner.

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
  "runtime": {
    "kind": "python",
    "version": "3.12"
  },
  "package_dependencies": {
    "python": [
      "python-dateutil>=2.9"
    ]
  },
  "callable_dependencies": [
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
  "callable_dependencies": [],
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
  "runtime": {
    "kind": "python",
    "version": "3.12"
  },
  "package_dependencies": {
    "python": [
      "pypdf==4.3.1"
    ]
  },
  "callable_dependencies": [
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

Nested local/app callable calls start their own invocation. The callee does not
run inside the caller's process. The caller asks the parent runtime to invoke the
declared callable dependency, and the parent starts or dispatches that dependency
under the correct scope, version, timeout, resource limits, and log context.

Core callables can be direct Python async functions because they ship with
Omnideck. Local and app callables must not run in-process with the Omnideck
server.

## Execution And Isolation

Hard requirement: callable code and callable package dependencies must never be
installed into, imported by, or executed inside the core Omnideck server runtime.
Local and app callables are external processes only.

This rules out:

- importing local/app callable implementation modules from the aiohttp process,
- running agent-authored code in-process,
- installing callable packages into Omnideck's Python environment,
- exposing provider or integration credentials through runner environment
  variables,
- letting runner package resolution mutate the core app environment.

The baseline execution model:

```text
Omnideck server process
  - loads core callables
  - validates manifests and schemas
  - prepares runner environments
  - starts local/app runner subprocesses
  - enforces callable dependency checks
  - stores logs/results
  - kills hung or over-budget runners

Callable runner process
  - uses its own runtime environment
  - imports callable package dependencies
  - executes user/app code
  - emits structured events and result
  - calls dependencies through parent-managed RPC
```

Each local/app callable invocation runs in its own process. That includes nested
callable-to-callable invocations. Separate processes give Omnideck crash
containment, timeout enforcement, memory cleanup, per-call attribution, clearer
logs, and centralized cancellation. Core callables may run in-process unless a
specific core callable opts into process execution.

The runner contract is language-neutral:

```text
input:  JSON args on stdin or RPC frame
output: JSON result or structured error
```

The first runner can be Python, but the protocol should support other runtimes
later. A manifest declares the runtime and implementation kind:

```json
{
  "runtime": { "kind": "python", "version": "3.12" },
  "implementation": { "kind": "python_script", "path": "implementation.py" }
}
```

Suggested process controls for v1:

- wall-clock timeout with process-group kill,
- CPU, memory, file-size, process-count, and file-descriptor limits where the
  host supports them,
- clean environment with no provider tokens, integration credentials, or
  Omnideck server `PYTHONPATH`,
- dedicated per-invocation working directory,
- app bundle and package environment treated as read-only where possible,
- no direct access to integration credentials.

This is not a complete hostile-code sandbox. It is runtime isolation from the
core Omnideck app plus resource controls. Stronger filesystem and network
sandboxing can layer on later with OS-level tools such as namespaces, cgroups,
seccomp, or bubblewrap.

## Useful Access Through Core Callables

Isolation cannot make callables useless. Local/app callables need to read and
write files, call HTTP APIs, use integrations, store app data, and call other
callables. Useful external effects should go through Omnideck core callables
where possible, not through broad ambient runner access.

Examples:

```text
omnideck.file.read@1
omnideck.file.write@1
omnideck.http.request@1
omnideck.app.storage.get@1
omnideck.app.storage.set@1
omnideck.email.create_draft@1
omnideck.drive.upload_file@1
```

Runner direct access should be narrow:

- writable invocation scratch directory,
- read-only app bundle/code,
- read-only prepared package environment where possible.

Everything else goes through declared callable dependencies and parent-managed
invocation. For example:

```python
result = await omnideck.invoke("omnideck.email.create_draft@1", {...})
```

The SDK call routes back through `invoke_callable(...)`, so dependency checks,
schema validation, call-stack limits, events, and broker enforcement stay in one
place.

The parent verifies:

- the target is declared in `callable_dependencies`,
- the caller's scope can resolve the target,
- the target input validates,
- the call graph does not exceed depth or recursion limits.

## Package Dependencies And Environment Cache

Callable package dependencies are installed into isolated runner environments,
not into the Omnideck app environment. Do not install into the server `.venv`,
system Python, or global npm.

Prepare environments by dependency-set hash rather than per callable:

```text
env_key = hash(runtime kind/version + package_dependencies + SDK version)
```

Storage:

```text
{settings.home_dir}/callable-envs/
  python/
    3.12/
      sha256_abcd1234/
        venv/
        metadata.json
```

Multiple callables with the same runtime and package dependencies reuse the same
environment. For Python, prefer a uv-managed environment cache so downloaded and
built wheels are shared without polluting the Omnideck server runtime.

Environment preparation should happen:

1. when a local callable is saved or tested,
2. when an app version is saved or imported,
3. lazily on first run if the environment is missing.

Preparation emits structured logs and install output. If dependency installation
requires unavailable system packages or fails, the callable should fail with an
actionable error. Do not let callables install OS packages.

Runner environments should be immutable after preparation. The callable process
runs in a separate writable work directory. If a platform cannot enforce
read-only mounts in v1, keep the design oriented around immutable envs so
OS-level hardening can enforce it later.

The environment cache also needs pruning:

- track `created_at`, `last_used_at`, dependency list, runtime, size, and status,
- delete unused failed/partial environments first,
- delete least-recently-used ready environments when the cache exceeds its size
  budget,
- never delete an environment currently in use by an active invocation.

## Logs, Events, And Debugging

Every invocation gets a `call_id` and a persisted run record:

```text
{settings.home_dir}/callable-runs/
  2026-07-05/
    call_abc123/
      metadata.json
      events.jsonl
      stdout.log
      stderr.log
      result.json
```

The runtime should capture:

- manifest id/version and implementation hash,
- caller context and app id/version when present,
- input validation errors,
- package environment preparation events,
- runner start/finish events,
- dependency call tree,
- stdout and stderr,
- structured result or error,
- timeout/resource-limit/cancellation details,
- duration and rough resource usage where available.

Example events:

```json
{ "type": "callable_started", "call_id": "call_abc123", "callable": "app.submit_invoice@1" }
{ "type": "dependency_call", "target": "omnideck.http.request@1" }
{ "type": "package_install", "package": "pypdf==4.3.1", "status": "started" }
{ "type": "error", "code": "CALLABLE_EXCEPTION", "message": "KeyError: invoice_total" }
{ "type": "callable_finished", "status": "error", "duration_ms": 824 }
```

Three audiences need these logs:

- maintainers, when a user exports a support bundle,
- users, when an app action or reusable automation fails,
- the agent, when it is debugging a callable it created or a tool binding it is
  trying to use.

Provide APIs/tools along these lines:

```text
list_callable_runs(callable_id?, app_id?, status?)
get_callable_run(call_id)
export_callable_support_bundle(call_id | app_id | date range)
```

Support bundles require explicit user action and should redact obvious secrets
from environment, stdout/stderr, events, and result payloads. Redaction is not a
security boundary, so avoid putting secrets into runner environments in the first
place.

## Log Retention And Pruning

Callable logs must be pruned so they cannot consume the user's disk.

Use a bounded run-log store with both age and size limits:

- configurable max total size for `callable-runs`,
- configurable max age for ordinary successful runs,
- separate, usually longer retention for failed runs,
- optional pinning for runs included in support bundles or active debugging
  sessions.

The pruner should run:

- at server startup,
- after each callable invocation finishes,
- after support bundle export,
- when the user manually requests cleanup.

Pruning order:

1. delete incomplete temp run directories from crashed writes,
2. delete oldest successful unpinned runs past age limit,
3. delete oldest failed unpinned runs past failure-retention limit,
4. if still above size budget, delete oldest unpinned runs regardless of status.

The pruner should never delete:

- active invocation logs,
- pinned support/debug runs,
- run metadata needed by currently open UI views.

The UI should expose current runtime storage usage and a cleanup action:

```text
Callable logs: 734 MB
Runtime environments: 1.8 GB
[Clean up unused runtime data]
```

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
