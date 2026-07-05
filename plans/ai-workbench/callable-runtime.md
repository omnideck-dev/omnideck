# Callable Runtime

> Detailed design for how Omnideck callables are packaged, stored, exposed to
> the agent, and invoked by apps and other callables.

## Core Model

A callable is versioned backend code with a manifest, input and output schemas,
package dependencies, callable dependencies, effects metadata, and a scope.
Core, local, and app callables use the same package format but live in different
roots.

Callables are language-neutral at the runtime boundary. The parent runtime talks
to every local/app callable over the same message protocol regardless of whether
the implementation is Python, JavaScript, Go, or another runtime later. Python
is the default and first-class runtime for v1 because it is the language the
agent can most reliably author today and it has the useful library ecosystem
apps need.

Most local and app callables will be agent-authored. Agent-buildability is a hard
design constraint: prefer a simple stable input/output/dependency protocol,
clear structured errors, discovery of available core callables and packages, and
a fast save/test loop over power that makes callables hard for the agent to
write correctly.

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

App exposure is also separate. The app bundle manifest declares each app
callable route's `app_visibility` as `public` or `private`; that bundle-level
inventory is the source of truth. The built-in app router can invoke public app
callables only. Private app callables can only be invoked by other app callables
in the same app version.

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

## Core Callable Version Lifecycle

Saved app versions vendor app and local callable code, but they do not vendor
Omnideck core callables. That makes core callable versions part of the stable
Omnideck runtime API. A saved or imported app that declares
`omnideck.http.request@1` must continue resolving that exact core callable id
after Omnideck upgrades.

Core callable ids use explicit API versions:

```text
omnideck.http.request@1
omnideck.http.request@2
omnideck.drive.upload_file@1
```

The `@N` suffix is a compatibility contract, not just an implementation build
number. Within one core callable version, Omnideck may:

- fix bugs,
- improve logging and diagnostics,
- tighten validation only when previously accepted inputs were invalid or
  unsafe,
- add optional input fields,
- add optional output fields,
- improve performance or resource limits without changing successful behavior.

Within one core callable version, Omnideck must not:

- remove accepted input fields,
- make optional fields required,
- rename or remove output fields,
- change error codes that app callables can branch on,
- change file-ref ownership or lifetime semantics,
- broaden effects beyond the manifest's declared effect family,
- reinterpret the same input to perform a materially different action.

Any breaking schema, behavior, error-shape, storage, file-ref, or effect change
creates a new core callable version. The old version remains registered and
invokable for saved apps that depend on it.

Retention rule for v1: keep every shipped core callable version for at least the
full support window of app import/export compatibility. Do not remove a core
callable version while any installed app version depends on it. If a version
must be disabled for a security reason, keep the id registered but make it fail
with a structured `CORE_CALLABLE_DISABLED` error that includes remediation
guidance, such as "update this app to use `omnideck.http.request@2`."

Deprecation is metadata, not removal:

```json
{
  "id": "omnideck.http.request",
  "version": "1",
  "scope": "core",
  "lifecycle": {
    "status": "deprecated",
    "replacement": "omnideck.http.request@2",
    "deprecated_at": "2027-01-15",
    "removal": "not before all installed/export-compatible app versions migrate"
  }
}
```

The app bundle manifest should record exact core dependencies, not open ranges:

```json
{
  "core_dependencies": [
    "omnideck.http.request@1",
    "omnideck.app.storage.get@1",
    "omnideck.drive.upload_file@1"
  ]
}
```

`requires.omnideck_core` may state the minimum Omnideck runtime family needed to
load the app, but callable resolution still uses the exact core callable ids in
`core_dependencies`. Import validation fails clearly when the target install
does not provide one of those ids.

When the agent updates an app, it may migrate app callables to newer core
versions and save a new app version. Existing saved app versions keep their old
core dependencies for rollback.

## Manifest Shape

Local and app callables should persist explicit JSON schemas in their manifests
so they can be validated, reviewed, bundled, and invoked without importing
arbitrary code first. Core callable schemas can be generated from typed Python
functions where that is clean, reusing the existing callable-to-tool-schema
machinery.

Manifests distinguish package dependencies from callable dependencies:

- `package_dependencies` are language/runtime packages installed into the
  callable runner environment, such as Python packages. Saved callables use
  exact versions and locks. Packages are either part of the curated baseline or
  explicitly approved extra packages.
- `callable_dependencies` are other Omnideck callables this callable may invoke
  through the parent-managed invocation API. They are never imported or installed
  into the runner.

Saved local/app callable manifests must specify exact package dependency
versions. Do not save open-ended ranges such as `>=2.9`, compatible-release
ranges such as `~=2.9`, wildcard versions, or unpinned package names in a saved
callable or app bundle. Draft tooling may accept loose requirements while the
agent experiments, but saving a local callable or app version must resolve them
to an exact lock and persist that exact dependency set.

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
    "python": {
      "baseline_packages": [
        "python-dateutil==2.9.0.post0"
      ],
      "approved_extra_packages": []
    }
  },
  "dependency_locks": {
    "python": "requirements.lock"
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

For compact examples elsewhere, `package_dependencies.python` may be shown as a
flat list of exact pins, but the persisted saved manifest should distinguish
baseline packages from user-approved extra packages.

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
      "integration_alias": { "type": "string" },
      "to": { "type": "array", "items": { "type": "string" } },
      "subject": { "type": "string" },
      "body": { "type": "string" }
    },
    "required": ["integration_alias", "to", "subject", "body"]
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
      "integration_alias": "Which app-level email alias to send through.",
      "to": "Recipient email addresses.",
      "subject": "Subject line.",
      "body": "Plain-text email body."
    },
    "runtime_hints": {
      "integration_alias": {
        "source": "integration_uses",
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
    "python": {
      "baseline_packages": [],
      "approved_extra_packages": [
        "pypdf==4.3.1"
      ]
    }
  },
  "dependency_locks": {
    "python": "requirements.lock"
  },
  "callable_dependencies": [
    "app.parse_invoice_pdf@1",
    "local.normalize_vendor@1",
    "omnideck.email.create_draft@1"
  ]
}
```

App callable package manifests never have `agent_binding`, and they do not
decide their own router visibility. The app bundle manifest is the source of
truth for `app_visibility`; if a callable package also contains an
`app_visibility` field, import/save validation should reject it instead of
trying to reconcile two authorities.

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
root_call_id: top-level invocation id
parent_call_id: optional direct parent call id
call_stack: callable refs already on this path
cancel_token: shared cancellation scope
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

Use one runner protocol for all local/app callables: a persistent parent-managed
RPC channel that stays open for the life of the runner process. Even simple
"input, output, finish" callables use this protocol. That avoids two execution
contracts and lets every callable emit events, observe cancellation, and call
declared dependencies if its manifest allows it.

Runner protocol sketch:

```text
parent -> runner: start { call_id, args, context, limits }
runner -> parent: event { ... }
runner -> parent: invoke_dependency { request_id, ref, args }
parent -> runner: dependency_result { request_id, result | error }
parent -> runner: cancel { reason }
runner -> parent: finish { result | error }
```

The parent owns dependency invocation. A runner cannot open another runner
directly. It can only send `invoke_dependency` over its parent channel. The
parent then validates the dependency declaration, detects recursion, starts the
child invocation, and returns the structured result or error.

Core callables can be direct Python async functions because they ship with
Omnideck. Local and app callables must not run in-process with the Omnideck
server.

## Call Graph Limits

The runtime must bound call chains before they hang or fork too many processes.
Suggested v1 limits:

| Limit | Default | Behavior on exceed |
|---|---:|---|
| Max call depth | 8 | Reject child invocation with `CALL_GRAPH_DEPTH_EXCEEDED` |
| Max repeated callable on one stack | 1 | Reject with `CALL_GRAPH_RECURSION` |
| Max child calls per root invocation | 64 | Reject further child calls with `CALL_GRAPH_FANOUT_EXCEEDED` |
| Max concurrent local/app runner processes per root invocation | 8 | Queue or reject with `CALL_GRAPH_CONCURRENCY_EXCEEDED` |
| Max global local/app runner processes | 32 | Queue globally, then timeout if capacity is unavailable |

Depth is counted from the top-level app/local callable. Core callables that run
in-process still appear in the call tree for diagnostics and effect summaries,
but the process-concurrency limits apply only to external local/app runners.

Recursion detection should happen before a child process starts. The parent
compares the requested callable ref against `call_stack`. For v1, disallow any
callable ref from appearing twice on the same stack. Later, a callable manifest
can opt into bounded recursion with explicit limits if a real use case appears.

Concurrency accounting is per root invocation and global. A child invocation
inherits the root `cancel_token`, root `call_id`, app context, and remaining
budget. If global capacity is exhausted, the parent may queue for a short bounded
time, for example 5 seconds, then fail with `CALL_GRAPH_CONCURRENCY_EXCEEDED`.

V1 accepts per-call process startup latency for local/app callables. That keeps
crash containment, cancellation, and attribution simple while the feature is
proven. App authors and the agent should avoid designs that call a local/app
dependency once per item in a tight loop; batch work into one callable, use
private helper functions inside the same callable package, or move hot loops
behind a core callable when the operation is privileged and audited. Persistent
runner pools or per-app warm runners are a later optimization only after real
latency data shows the process-per-call model is blocking interactive workflows.

## Execution And Isolation

Hard requirement: callable code and callable package dependencies must never be
installed into, imported by, or executed inside the core Omnideck server runtime.
Local and app callables are external processes only. Dependency installation for
their package environments also runs outside the Omnideck server runtime.

Native process runners are the v1 model. Do not revisit WASM engines, microVMs,
or nested virtualization for v1. They either do not run the ordinary package
ecosystem callables need or require host/container powers this design rejects.
Usefulness requires normal language runtimes and packages, confined by the
self-restricting launcher and the container boundary.

This rules out:

- importing local/app callable implementation modules from the aiohttp process,
- running agent-authored code in-process,
- installing callable packages into Omnideck's Python environment,
- exposing provider or integration credentials through runner environment
  variables,
- letting runner package resolution mutate the core app environment,
- running package build/install hooks inside the Omnideck server process.

The baseline execution model:

```text
Omnideck server process
  - loads core callables
  - validates manifests and schemas
  - schedules isolated runner environment preparation
  - requests runner launches from the privileged runner launcher
  - enforces callable dependency checks
  - stores logs/results
  - kills hung or over-budget runners

Environment builder process
  - runs outside the Omnideck server runtime
  - creates dependency environments
  - executes package install/build hooks under the builder sandbox floor
  - emits install logs and metadata
  - never receives credentials

Callable runner process
  - uses its own runtime environment
  - imports callable package dependencies
  - executes user/app code
  - emits structured events and result
  - calls dependencies through parent-managed RPC
```

### Container Boundary And Threat Model

The Omnideck container is the boundary to the host, and it stays that way.
Nothing in the callable runtime may require adding privileges to the container
or weakening its host isolation. That rules out user namespaces, bubblewrap and
other namespace sandboxes, host network-namespace tricks, gVisor, and microVMs,
because each needs the container or deployment to be granted power it does not
have today. If Omnideck ever stops running in a container, a stronger outer
boundary is a separate future design.

Inside the container, the runner sandbox is defense in depth, not the host
boundary. The worst outcome for a misbehaving callable is that it is confined to
its own unprivileged user inside the container, which the container already keeps
away from the host.

### Dedicated Runner User

Local and app callables run as dedicated unprivileged OS users. The prototype
name is `runner`, but v1 should provision a distinct runner uid per app install
and per local-callable trust domain, for example `runner_app_<id>` and
`runner_local`. Do not use one shared runner uid for all apps. Runner users own
no user data and are not in the `broker` group, so they cannot open broker
sockets or reach the vault. Core callables keep running in the `omnideck`
process. Only untrusted local/app callable code runs as runner users.

Switching users must not require adding anything to the container. The design
assumes the existing container boot path already starts with enough privilege to
drop from root to `omnideck` and `broker`, using the default container
`CAP_SETUID` and `CAP_SETGID` capabilities. This assumption must be verified in
the container implementation. A small launcher, started at boot like the
supervisor, is the only component that retains the ability to drop to runner
uids. The Omnideck server asks the launcher over a private control socket to
start a callable; the launcher validates the request, opens the inherited
control/spool descriptors, drops to the app-specific runner uid, applies the
sandbox below, and execs the runner. Setuid capability stays in that launcher,
never in the agent-facing Omnideck app.

The launcher is a standing privileged component and must stay small, audited, and
non-agent-facing. It should accept only structured launch requests from the
Omnideck server, never arbitrary shell commands or paths from app code.

There are three file areas:

- runner OS scratch: a private writable temp directory owned by the app-specific
  runner uid and deleted after the invocation,
- managed invocation files: Omnideck-owned files that become opaque `file_ref`
  values through core file callables,
- app data/export files: durable Omnideck-owned app storage and export roots.

The runner can write freely only in runner OS scratch. Files that need to leave
the runner, including outputs above the inline JSON cap, use a parent-managed
spool descriptor. The launcher/parent opens a file in the managed invocation
area as `omnideck`, passes the open write descriptor to the runner across
fork/setuid/exec or later via `SCM_RIGHTS` over the inherited control socket, and
the runner streams bytes into that descriptor. The runner never receives the host
path and could not open it itself. The parent seals the file, records metadata,
and returns an opaque `file_ref`.

### Self-Applied Sandbox

The launcher applies these controls to the runner process before any callable
code runs. Every one only removes power and needs nothing granted to the
container:

- the non-root app-specific runner user, with no group memberships that grant
  app data or broker access,
- `NO_NEW_PRIVS`, so the process and its children can never regain privileges by
  exec,
- all Linux capabilities dropped, including the bounding set,
- a seccomp filter allowing only the syscalls a runner needs; this shrinks the
  kernel attack surface and denies the network by blocking new socket creation,
  so a callable reaches the outside world only through core callables; the
  profile must still allow I/O on inherited descriptors and `sendmsg`/`recvmsg`
  where needed for `SCM_RIGHTS` descriptor passing,
- Landlock confining the filesystem to runner OS scratch plus read-only access
  to the callable's code and package environment,
- resource limits for CPU time, memory, file size, open files, and process
  count, and disabled core dumps,
- a clean environment with no provider tokens, integration credentials, or
  server import paths.

The parent enforces a wall-clock timeout and kills the runner's process group if
it exceeds its budget or ignores cancellation.

V1 execution floor: app/local callable execution is disabled unless the launcher
can enforce the non-root app-specific runner uid, no-new-privs, dropped
capabilities, seccomp network denial, resource limits, disabled core dumps, and
Landlock filesystem confinement. A developer-only unsafe mode may exist for
local experimentation, but imported apps and normal user apps must not run in
that mode.

This is runtime isolation inside the container, not a jail against kernel
exploits. The container remains the host boundary.

### Real Power Boundary

The runner can do nothing directly. Its only capability is to ask the parent to
invoke a core callable. The security of the model is therefore set by how narrow
and well-audited the core-callable surface is, not by the runner user alone.
Core callables run as `omnideck` on input from untrusted callable code, which
makes each one a privileged trust boundary.

Every core callable must validate its inputs accordingly. No core callable may
hand a callable broad ambient power, such as a general "run a shell command"
callable. One careless core callable can undo the model.

Each local/app callable invocation runs in its own process. That includes nested
callable-to-callable invocations. Separate processes give Omnideck crash
containment, timeout enforcement, memory cleanup, per-call attribution, clearer
logs, and centralized cancellation. Core callables may run in-process unless a
specific core callable opts into process execution.

The runner contract is language-neutral and RPC-based:

```text
transport: parent-managed stdio, socketpair, or equivalent local channel
input:     start frame with JSON args and context
output:    finish frame with JSON result or structured error
side calls: dependency invocation frames over the same channel
control:   cancellation and heartbeat frames over the same channel
```

Do not add a separate stdin-only runner mode for "simple" callables in v1. One
protocol everywhere is easier to test, easier to cancel, and avoids guessing
whether a callable will ever need dependency calls.

The first runner can be Python, but the protocol should support other runtimes
later. A manifest declares the runtime and implementation kind:

```json
{
  "runtime": { "kind": "python", "version": "3.12" },
  "implementation": { "kind": "python_script", "path": "implementation.py" }
}
```

Suggested data limits for v1:

| Limit | Default |
|---|---:|
| Max JSON args size | 1 MB |
| Max JSON result size | 1 MB |
| Max single event frame size | 256 KB |
| Max stdout captured per call | 1 MB |
| Max stderr captured per call | 1 MB |
| Max scratch bytes per call | 128 MB |

Large outputs must become managed file refs through core file callables instead
of being returned inline. If a callable returns a result over the JSON cap, the
runtime fails validation with `CALLABLE_RESULT_TOO_LARGE` and records the
oversize attempt in the run log.

## Useful Access Through Core Callables

Isolation cannot make callables useless. Local/app callables need to read and
write files, call HTTP APIs, use integrations, store app data, and call other
callables. Useful external effects should go through Omnideck core callables
where possible, not through broad ambient runner access.

Runner processes do not get their own network path. Anything outside the runner
comes through core callables, and integration-backed core callables still go
through the broker with existing credentials and permissions. This keeps the
single door to the outside world under Omnideck control and keeps credentials out
of callable code.

See [core-callables.md](core-callables.md) for the first concrete surface for
app-scoped storage, files/artifacts, HTTP/API requests, integration wrappers,
and the rule that user-visible files are promoted through artifact callables
rather than written to arbitrary host paths.

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

- writable runner OS scratch directory,
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

## Cancellation

Cancellation is rooted at the top-level invocation. Every nested dependency call
inherits the same `root_call_id` and `cancel_token`, so the runtime can cancel
the entire call tree.

When a user or router cancels a top-level action:

1. Mark the root run as cancelling.
2. Send `cancel` frames to every active runner in the call tree.
3. Stop accepting new `invoke_dependency` requests for that root.
4. Cancel or timeout active core callable operations where possible.
5. Wait a short grace period, for example 2 seconds.
6. Kill remaining local/app runner process groups.
7. Mark unfinished child calls as `CALLABLE_CANCELLED`.
8. Mark the root call as `CALLABLE_CANCELLED`.

Cancellation must be transitive. It is a runtime bug if only the top-level
runner is cancelled while child runner processes continue running.

Every run record should include enough parent/child metadata to reconstruct and
cancel the active call tree:

```text
root_call_id
call_id
parent_call_id
children
process_group_id
status
cancel_token
```

If a runner receives cancellation and exits cleanly, preserve its partial logs
and final cancellation event. If it ignores cancellation, kill the process group
and record `CALLABLE_KILLED_AFTER_CANCEL`.

## Package Dependencies And Environment Cache

Callable package dependencies are installed into isolated runner environments,
not into the Omnideck app environment. Do not install into the server `.venv`,
system Python, or global npm.

Use a baseline-plus-consented-long-tail model:

- `baseline_packages` are curated, common, vetted packages available by default
  for a runtime. They make agent-authored callables fast and predictable.
- `approved_extra_packages` are packages outside the baseline that the user has
  explicitly approved for a callable or app because installing them runs package
  code.

The agent should be able to discover the baseline package set before building a
callable. If it needs an extra package, the save/test flow must surface that
request for user approval before installation.

V1 Python baseline package set, maintained as a runtime-owned manifest with exact
pins:

```text
python-dateutil==2.9.0.post0
pydantic==2.8.2
jsonschema==4.23.0
PyYAML==6.0.2
beautifulsoup4==4.12.3
lxml==5.2.2
markdown-it-py==3.0.0
numpy==2.0.1
pandas==2.2.2
scikit-learn==1.5.1
```

This is a starter baseline derived from the first expected app families:
backlog/project tools, data cleanup, parsing/scraping, document-ish text
processing, and lightweight classification. The exact pins can change before
implementation lands, but the shipped runtime must expose the active exact list
through discovery. Saved callable manifests record which baseline packages they
use. The saved app bundle manifest records the user-facing review decision for
packages outside this baseline under `package_review.approved_extra_packages`;
callable manifests record the same exact pins under
`package_dependencies.*.approved_extra_packages` so the environment builder has
a local package input. If these disagree, save/import validation fails.

Saved local/app callables use exact package dependencies only. A saved callable
or saved app version must be reproducible from its manifest and, where the
language ecosystem supports it, a lock file generated at save time:

```text
callables/backup_project/
  manifest.json
  requirements.lock
  implementation.py
```

For Python, `manifest.json` lists exact top-level requirements and
`requirements.lock` records the fully resolved transitive set with exact
versions and hashes when available. Drafts may start from loose requirements,
but save/import must fail until dependency resolution produces an exact lock.

Prepare environments by dependency-set hash rather than per callable:

```text
env_key = hash(runtime kind/version + locked dependency set + SDK version)
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

Multiple callables with the same runtime and locked dependencies may reuse the
same environment only after it has been sealed immutable. For Python, prefer a
uv-managed environment cache so downloaded wheels are shared without polluting
the Omnideck server runtime.

Environment preparation should happen:

1. when a local callable is saved or tested,
2. when an app version is saved or imported,
3. lazily on first run if the environment is missing.

Preparation runs in an isolated environment builder process, not in the
Omnideck server process. Use a dedicated build user, not the app runner uid. The
Omnideck server requests builder launches from the same privileged launcher, or
a sibling launcher with the same narrow contract. The launcher validates a
structured `build_environment` request, opens only the required scratch/cache
descriptors, drops to the dedicated build uid, applies the builder sandbox, and
execs the builder. App code and package hooks never choose builder paths or
launcher commands.

Builder execution floor: environment preparation is disabled unless the launcher
can enforce the non-root dedicated build user, `NO_NEW_PRIVS`, dropped
capabilities, seccomp network denial for hook execution, resource limits,
disabled core dumps, and Landlock filesystem confinement. The builder has no
provider tokens, no integration credentials, no broker group, no Omnideck server
`PYTHONPATH`, and no access to app runner scratch.

Split fetch from build:

1. A trusted fetch step downloads exact packages from configured package indexes
   into a content-addressed package cache and verifies each artifact against the
   lock file hash.
2. Package install/build hooks run offline with network creation denied by
   seccomp. Hooks receive the package cache read-only and can write only to
   builder scratch and the in-progress environment directory.
3. The completed environment is verified, then sealed read-only and owned by
   Omnideck/runtime storage before any callable can reuse it.

If a package requires arbitrary network during build, unavailable system
packages, or mutable post-install state, environment preparation fails with an
actionable error. Build hooks never execute with app, credential, or reusable
environment or shared package-cache write access, so one callable cannot poison
a shared env or package cache for another. Before reuse, package artifacts are
hash-verified against the lock file again.

Preparation emits structured logs and install output. If dependency installation
requires unavailable system packages or fails, the callable should fail with an
actionable error. Do not let callables install OS packages.

Runner environments must be immutable after preparation. The callable process
runs in a separate writable work directory. If the platform cannot enforce a
read-only prepared environment, normal/imported app execution for that
environment fails instead of reusing a mutable shared environment.

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
- call graph limit errors,
- duration and rough resource usage where available.

Example events:

```json
{ "type": "callable_started", "call_id": "call_abc123", "callable": "app.submit_invoice@1" }
{ "type": "dependency_call", "target": "integration.github.request@1", "alias": "github" }
{ "type": "package_install", "package": "pypdf==4.3.1", "status": "started" }
{ "type": "error", "code": "CALLABLE_EXCEPTION", "message": "KeyError: invoice_total" }
{ "type": "callable_finished", "status": "error", "duration_ms": 824 }
```

Common runtime error codes:

| Code | Meaning |
|---|---|
| `CALL_GRAPH_DEPTH_EXCEEDED` | Child invocation would exceed max depth |
| `CALL_GRAPH_RECURSION` | Callable ref already appears on the active call stack |
| `CALL_GRAPH_FANOUT_EXCEEDED` | Root invocation has started too many child calls |
| `CALL_GRAPH_CONCURRENCY_EXCEEDED` | Per-root or global runner concurrency is exhausted |
| `CALLABLE_RESULT_TOO_LARGE` | JSON result exceeded the inline result cap |
| `CALLABLE_CANCELLED` | Invocation was cancelled by user/client/runtime |
| `CALLABLE_KILLED_AFTER_CANCEL` | Runner ignored cancellation and was killed |
| `DEPENDENCY_LOCK_REQUIRED` | Saved callable has loose or missing package lock |
| `DEPENDENCY_INSTALL_FAILED` | Isolated dependency preparation failed |

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
local.normalize_bank_csv@1
app.submit_invoice@1
```

Core ids are stable API families owned by Omnideck. Local ids are private to the
install. App ids are meaningful only inside an app bundle. If standalone
callable sharing is added later, it can introduce community or publisher
namespaces, but that is not needed for the first version.

Each packaged app version has a manifest. The manifest is both the reviewable
contract and the bundled-content inventory. Avoid a separate app-level package
manager lockfile for v1. Since app versions vendor the code they need, bundle
hashes can live directly in the app manifest. Individual callable packages still
carry exact dependency locks such as `requirements.lock` when they declare
package dependencies:

```json
{
  "id": "app.invoice_dashboard",
  "version": "3",
  "requires": {
    "omnideck_core": ">=1"
  },
  "core_dependencies": [
    "omnideck.email.create_draft@1",
    "omnideck.app.storage.get@1",
    "omnideck.app.storage.set@1"
  ],
  "callables": {
    "submit_invoice": {
      "id": "app.submit_invoice",
      "version": "1",
      "app_visibility": "public",
      "path": "callables/submit_invoice/",
      "sha256": "..."
    },
    "parse_invoice_pdf": {
      "id": "app.parse_invoice_pdf",
      "version": "1",
      "app_visibility": "private",
      "path": "callables/parse_invoice_pdf/",
      "sha256": "..."
    }
  },
  "vendored_callables": {
    "local.normalize_vendor": {
      "id": "local.normalize_vendor",
      "version": "1",
      "path": "vendor/local.normalize_vendor/",
      "sha256": "..."
    }
  }
}
```

The hash is tamper evidence and supports exact rollback. It does not mean the
code is trusted. Review, isolation, and broker enforcement still matter.
