# Callable runtime prototype

A minimal, runnable slice of the callable runtime design in
`plans/ai-workbench/callable-runtime.md`. It exists to prove the one mechanic
the design hinges on: a callable running in its own process can call another
callable, brokered by the parent, with limits and schema checks enforced in one
place.

## Run

```sh
python3 demo.py
```

No dependencies, no container, no broker. Standard library only.

## What it proves

- The single `invoke_callable(ref, args, ctx)` entry point resolves a callable
  from on-disk manifests, checks the caller, validates args, dispatches, and
  validates the result.
- Core callables run in-process via a `python_import` target.
- Local callables run in a subprocess runner over one persistent parent-managed
  RPC channel (`start`, `invoke_dependency`, `dependency_result`, `finish`),
  the single protocol from the design.
- A runner never opens another runner. It sends `invoke_dependency` to the
  parent, which recurses through `invoke_callable`. This is demonstrated one and
  two levels deep, subprocess calling subprocess calling in-process core.
- The call-graph limits are enforced by the parent: declared-dependency
  allow-list, recursion (a ref twice on the stack), and per-root fanout.
- Args and results are validated against the manifest JSON schemas at the
  boundary.

## What it stubs (on purpose)

These are specified in the design but out of scope for proving the core loop:

- package-dependency environments and the isolated env builder (uses the
  current interpreter, installs nothing),
- OS-level sandboxing (plain subprocess, no cgroups/seccomp/namespaces),
- on-disk run logs and pruning (events are collected in memory),
- user-initiated cancellation and heartbeats (frames are defined but not
  exercised),
- depth-limit and concurrency-cap behavior under real fanout (limits are coded;
  the demo drives fanout and recursion, not the depth or global-concurrency
  caps),
- the apps, app bundle, and app-router layer.

## Files

- `runtime.py` — registry, `invoke_callable`, call-graph limits, subprocess
  runner management.
- `runner.py` — the subprocess harness and the in-runner `omni.invoke` SDK.
- `frames.py` — length-prefixed JSON framing (blocking for the runner, asyncio
  for the parent).
- `validate.py` — a tiny JSON Schema subset validator.
- `core_impls.py` — in-process core callable implementations.
- `callables/` — on-disk callable packages (manifest plus implementation).
- `demo.py` — the scenarios and their expected outcomes.
