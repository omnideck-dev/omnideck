#!/usr/bin/env python3
"""Drive pkttyagent for one disposable-VM application process."""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import pty
import re
import select
import signal
import time


def process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", type=int, required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    arguments = parser.parse_args()

    password = arguments.password_file.read_bytes().rstrip(b"\r\n")
    if not password:
        raise SystemExit("The disposable guest password is empty")
    arguments.log.parent.mkdir(parents=True, exist_ok=True)

    notification_read, notification_write = os.pipe()
    agent_pid, terminal = pty.fork()
    if agent_pid == 0:
        os.close(notification_read)
        os.set_inheritable(notification_write, True)
        os.execvp(
            "pkttyagent",
            [
                "pkttyagent",
                "--process",
                str(arguments.process),
                "--notify-fd",
                str(notification_write),
            ],
        )

    os.close(notification_write)
    prompt_buffer = b""
    password_responses = 0
    ready = False
    exit_status = 1
    try:
        with arguments.log.open("ab", buffering=0) as log:
            log.write(
                f"agent-start target={arguments.process} agent={agent_pid}\n".encode()
            )
            while True:
                readable, _, _ = select.select(
                    [notification_read, terminal], [], [], 0.25
                )
                if notification_read in readable:
                    os.read(notification_read, 64)
                    if not ready:
                        arguments.ready_file.touch()
                        log.write(b"agent-ready\n")
                        ready = True
                if terminal in readable:
                    try:
                        chunk = os.read(terminal, 4096)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        log.write(chunk.replace(password, b"[REDACTED]"))
                        prompt_buffer = (prompt_buffer + chunk)[-8192:]
                        if re.search(rb"password\s*:", prompt_buffer, re.IGNORECASE):
                            os.write(terminal, password + b"\n")
                            password_responses += 1
                            log.write(
                                f"\n[disposable password supplied response={password_responses}]\n".encode()
                            )
                            prompt_buffer = b""
                waited_pid, waited_status = os.waitpid(agent_pid, os.WNOHANG)
                if waited_pid:
                    exit_status = os.waitstatus_to_exitcode(waited_status)
                    break
                if not process_exists(arguments.process):
                    os.kill(agent_pid, signal.SIGTERM)
            log.write(
                f"agent-exit status={exit_status} responses={password_responses}\n".encode()
            )
    finally:
        os.close(notification_read)
        os.close(terminal)
        arguments.ready_file.unlink(missing_ok=True)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
