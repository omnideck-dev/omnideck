#!/usr/bin/env python3
"""Own a Windows-lab SSH tunnel across shell subshells on the Linux controller."""

import argparse
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys
import time
from typing import TypedDict


class TunnelIdentity(TypedDict):
    pid: int
    startTicks: str
    command: list[str]


def identity(pid: int) -> TunnelIdentity:
    proc = Path('/proc') / str(pid)
    fields = proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()
    if fields[0] == 'Z':
        raise ProcessLookupError(pid)
    return {
        'pid': pid,
        'startTicks': fields[19],
        'command': [os.fsdecode(arg) for arg in proc.joinpath('cmdline').read_bytes().split(b'\0') if arg],
    }


def record(path: Path, pid: int, command: list[str]) -> None:
    # Popen/fork returns before exec has necessarily replaced the shell image.
    deadline = time.monotonic() + 2
    while True:
        current = identity(pid)
        if current['command'] == command:
            break
        if time.monotonic() >= deadline:
            raise ValueError('Tunnel process command did not match the launched command')
        time.sleep(0.01)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(current) + '\n')
    temporary.replace(path)


def start(path: Path, command: list[str], log: Path) -> int:
    with log.open('wb') as output:
        child = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    try:
        record(path, child.pid, command)
    except BaseException:
        # This is our unreaped child, so its PID cannot be reassigned. Never
        # leave a spawned tunnel behind if its ownership receipt cannot persist.
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
        raise
    return child.pid


def stop(path: Path, command: list[str]) -> None:
    if not path.exists():
        return
    expected = json.loads(path.read_text())
    if expected['command'] != command:
        raise ValueError('Refusing to stop a tunnel belonging to a different command')
    descriptor = None
    try:
        # A pidfd also prevents PID reuse between validation and signaling.
        descriptor = os.pidfd_open(expected['pid'])
        if identity(expected['pid']) != expected:
            raise ValueError('Refusing to stop a reused or changed tunnel process')
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        exited = select.poll()
        exited.register(descriptor, select.POLLIN)
        if not exited.poll(3000):
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            if not exited.poll(2000):
                raise TimeoutError('The owned tunnel did not exit; retaining its receipt')
    except (FileNotFoundError, ProcessLookupError):
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
    path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'record', 'stop'))
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--log', type=Path)
    arguments = sys.argv[1:]
    separator = arguments.index('--') if '--' in arguments else len(arguments)
    args = parser.parse_args(arguments[:separator])
    command = arguments[separator + 1:]
    if not sys.platform.startswith('linux') or not command:
        parser.error('This VM-controller helper requires Linux and the exact tunnel command')
    if args.action == 'start':
        if args.log is None:
            parser.error('start requires --log')
        print(start(args.receipt, command, args.log))
    elif args.action == 'record':
        if args.pid is None:
            parser.error('record requires --pid')
        record(args.receipt, args.pid, command)
    else:
        stop(args.receipt, command)


if __name__ == '__main__':
    main()
