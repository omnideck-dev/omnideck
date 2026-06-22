---
title: Sandboxed Code Execution
type: concept
tags: [bash, execution, security, policy, container]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]"]
---

# Sandboxed Code Execution

## Overview

Code execution in Omnideck runs directly inside the container as the `computron` user (not in a nested sandbox like Podman). The "sandboxing" is the container boundary itself plus an execution policy (deny-list patterns). Commands run under `set -euo pipefail` with a configurable timeout and process group kill on timeout.

## How It Works

**`run_bash_cmd(cmd, timeout=120)`:**
1. Check execution policy (`_policy.py` deny patterns)
2. Prepend `set -euo pipefail;` to the command
3. Publish "running" event
4. Start subprocess with `start_new_session=True` (new process group)
5. Concurrently read stdout/stderr, publishing "streaming" events in 4KB chunks
6. Wait for completion (timeout enforced via `asyncio.wait_for`)
7. On timeout: `os.killpg(pid, SIGKILL)` kills entire process tree
8. Publish "completed" event with final stdout/stderr/exit_code

**Execution policy:** `_policy.py` contains deny patterns checked before any command runs. Commands matching deny patterns return exit_code=126 with an error message. (Details of deny patterns not fully explored — TODO: read `_policy.py`)

**Process group kill:** `start_new_session=True` makes the bash process a process group leader; `os.killpg` ensures grandchild processes are also killed on timeout (e.g., long-running npm install)

**Package installation promotion:** `install_packages()` auto-runs package manager commands with elevated permissions (the container runs as computron, sudo is configured)

**Event streaming:** `TerminalOutputPayload` with `status="streaming"` fires in real-time as output is produced, allowing the UI to show live output

**Working directory:** `config.virtual_computer.home_dir` (the agent's home dir inside the container)

## Key Details

- Note from DEVELOPMENT.md: CLAUDE.md says "Podman for sandboxed code execution" but the current implementation runs directly inside the container — this may be a legacy description or a planned feature
- `set -euo pipefail` means any command failing causes the script to exit; `set -u` catches unbound variables; `pipefail` propagates pipe failures
- Long-running processes should be backgrounded with `&` — the tool will time out otherwise
- Timeout default 120s can be overridden per call for known-slow operations

## Open Questions

- What exactly is in `_policy.py`'s deny patterns? Not fully read.
- Is Podman actually used for any execution sandboxing, or is it purely the container boundary?

## Sources

- [[Source - Tools Overview]]
