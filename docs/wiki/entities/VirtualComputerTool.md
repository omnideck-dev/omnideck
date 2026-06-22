---
title: VirtualComputerTool
type: entity
tags: [virtual-computer, file-system, bash, execution, tools]
created: 2026-06-22
updated: 2026-06-22
sources: ["[[Source - Tools Overview]]"]
---

# VirtualComputerTool

## Overview

The virtual computer tools (in `tools/virtual_computer/`) provide the agent with a file system interface and bash execution capability within the container. The agent treats the container's home directory (`config.virtual_computer.home_dir`) as its workspace.

## Details

**File operations:**
- Read: `read_file(path)`, `head(path, n)`, `tail(path, n)`
- Write: `write_file(path, content)`, `write_files(files)`, `append_to_file(path, content)`, `prepend_to_file(path, content)`
- Edit: `insert_text(path, line_number, text)`, `replace_in_file(path, old, new)`, `apply_text_patch(path, patch)`, `apply_unified_diff(path, diff)`
- Navigation: `list_dir(path)`, `path_exists(path)`, `exists(path)`, `is_file(path)`, `is_dir(path)`
- Management: `make_dirs(path)`, `remove_path(path)`, `copy_path(src, dst)`, `move_path(src, dst)`
- Search: `grep(pattern, path)` — returns `GrepResult` with `GrepMatch` objects

**Bash execution (`run_bash_cmd`):**
- Runs under `set -euo pipefail` (strict mode)
- Default 120s timeout; can override per call
- Publishes `TerminalOutputPayload` events: "running" before, "streaming" during, "completed" after
- Execution policy (`_policy.py`): deny patterns checked before execution (e.g., dangerous system commands)
- Process group kill on timeout/cancel (uses `os.killpg` to kill entire process tree)
- Auto-promotes package installs (pip, npm, apt) to root

**Package installation:** `install_packages(packages)` — higher-level package install wrapper

**File sharing:**
- `send_file(path)` — emits `FileOutputPayload` event so UI offers file download
- `receive_attachment(base64_encoded, content_type, filename)` — writes uploaded file to container, returns container path

**Other:**
- `describe_image(path)` — uses vision model to describe an image file
- `play_audio(path)` — emits `AudioPlaybackPayload` for browser playback

## Related Entities

- [[BrowserTool]] (complementary tool set)
- [[TerminalOutputPayload]] (emitted by `run_bash_cmd`)
- [[FileOutputPayload]] (emitted by `send_file`)
- [[AgentState]] (tools registered here)
- [[AppConfig]] (`virtual_computer.home_dir`)

## Sources

- [[Source - Tools Overview]]
