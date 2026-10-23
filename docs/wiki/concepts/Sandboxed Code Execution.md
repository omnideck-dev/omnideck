---
title: Sandboxed Code Execution
type: concept
tags: [virtual-computer, tools, agent, bash]
created: 2026-10-18
updated: 2026-10-18
verified_commit: 3b839a12
paths:
  - "tools/virtual_computer/"
---

# Sandboxed Code Execution

## Overview

The **virtual computer** is the agent's file system and shell — a home directory
(configured via `cfg.virtual_computer.home_dir`, mounted at `/home/computron` in the
container) where the agent reads, writes, edits, and executes code. It's not a
per-call sandbox like a gVisor/Firecracker microVM — isolation comes from the
container boundary itself plus a command-level deny-list; everything inside the
container runs as the `computron` OS user.

## How It Works

### 1. File operations

`tools/virtual_computer/file_ops.py`, `read_ops.py`, `edit_ops.py`, `stat_ops.py`,
`search_ops.py`, `patching.py` implement the actual file primitives — `write_file`,
`read_file`/`head`/`tail`, `list_dir`, `grep`, `apply_text_patch`/`apply_unified_diff`,
`move_path`/`copy_path`/`remove_path`, `make_dirs`, `path_exists`. `search_ops.py`
delegates to a worker (`_search_worker.py`) for grep-style search across files.
`models.py` defines the shared result types (`GrepResult`, `DirEntry`,
`ReadFileError`, etc.) these return.

### 2. Bash execution and its deny-list

`tools/virtual_computer/run_bash_cmd.py:run_bash_cmd()` runs an arbitrary shell
command and streams output via `publish_event(AgentEvent(payload=TerminalOutputPayload(...)))`
— see [[Event System]]. Before running, `tools/virtual_computer/_policy.py:
is_allowed_command()` checks the command string against a fixed set of deny
patterns — **not** a sandbox, a blocklist: it blocks things that look like a
long-running dev server or watcher (`npm run dev`, `vite dev`, `tail -f`, `watch`,
`--watch` flags, `sleep infinity`, `python -m http.server`, headed Playwright), on
the theory that a tool call is expected to return, not block forever. Anything not
matching a deny pattern is allowed — including destructive commands; there's no
allow-list and no privilege separation beyond the container.

### 3. Package installation

`tools/virtual_computer/install_packages.py:install_packages()` runs `pip install`
inside the container for the agent's own Python environment.

### 4. Other virtual-computer tools

- `file_output.py:send_file()` — marks a file for UI download, emitting a
  `FileOutputPayload` event (see [[Event System]]).
- `receive_file.py` — writes an uploaded attachment to disk.
- `describe_image.py` — vision-model description of an image file.
- `play_audio.py` — plays an audio file (desktop-adjacent, still under this package).

### 5. Custom tools build on this sandbox

`tools/custom_tools/executor.py` (see [[Tool Architecture]]) reuses the same
container/home-directory boundary — a `program`-type custom tool's script is written
under `<virtual_computer.home_dir>/custom_tools/scripts/` and invoked with
`bash -c "echo <json-args> | <python3|bash> <script>"`. No sandboxing beyond that.

## Where It Lives

| Path | Role |
|------|------|
| `tools/virtual_computer/_policy.py` | `is_allowed_command()` — the bash deny-list |
| `tools/virtual_computer/run_bash_cmd.py` | `run_bash_cmd()`, `BashCmdResult` |
| `tools/virtual_computer/file_ops.py`, `read_ops.py`, `edit_ops.py`, `patching.py`, `stat_ops.py`, `search_ops.py` | File primitives |
| `tools/virtual_computer/install_packages.py` | `pip install` inside the container |
| `tools/virtual_computer/file_output.py`, `receive_file.py` | UI file transfer |
| `tools/virtual_computer/models.py` | Shared result/data models |

## Key Details

- **`_policy.py` has no project imports on purpose** ("pure validation logic... safe
  to import without triggering circular dependencies" per its own docstring) — keep it
  that way if extending the deny-list.
- **The deny-list is a heuristic, not a security boundary.** It exists so a single
  tool call can't hang the turn loop on a process that never exits; it is not
  positioned (in the code or its comments) as a defense against a malicious or
  misbehaving agent.
- **All file paths resolve against `virtual_computer.home_dir`** — there's no
  documented path-escape guard found directly in `file_ops.py`/`read_ops.py`
  themselves in this pass; confirm before relying on this as a containment boundary
  if that matters for your use case (flagged as an open question below).

## Open Questions

- Whether file-path operations (`write_file`, `read_file`, etc.) actively reject
  paths that escape the home directory (e.g. via `../../`), or rely entirely on the
  container filesystem boundary, was not confirmed by this pass — worth a follow-up
  read of `_fs_internal.py` if path containment matters for a specific task.

## Sources

- None beyond source code.
