"""Generic e2e infrastructure helpers — container interaction, etc.

Not pytest fixtures — plain functions imported by the test files
that need them. Anything that needs pytest discovery belongs in
conftest.py or a registered plugin module.
"""

import os
import subprocess

CONTAINER_NAME = os.environ.get("OMNIDECK_CONTAINER", "omnideck_e2e")


def container_exec(script: str) -> str:
    """Run a Python snippet inside the running omnideck container.

    Used for seeding state that has no HTTP API (goals, runs, etc.). The
    snippet executes in the same Python environment as the running app —
    `from tasks import get_store` works, file writes land in the volume
    the app reads from.

    Runs as `omnideck` (the user the app runs as) so any files written
    are owned by the same uid as the app process. Otherwise the app's
    later cleanup hits a PermissionError.
    """
    result = subprocess.run(
        ["docker", "exec", "-u", "omnideck", "-w", "/opt/omnideck",
         CONTAINER_NAME, "python3.12", "-c", script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def push_file_to_container(host_path: str, container_path: str) -> None:
    """Copy a host file into the running container, owned by the app user.

    For seeding files the app or its sandboxed browser must read (e.g. an HTML
    fixture served from the container home). ``docker cp`` lands the file as
    root, so it's chowned to ``omnideck`` to match the app's uid.
    """
    subprocess.run(
        ["docker", "cp", host_path, f"{CONTAINER_NAME}:{container_path}"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["docker", "exec", "-u", "0", CONTAINER_NAME,
         "chown", "omnideck:omnideck", container_path],
        capture_output=True, text=True, check=True,
    )


def container_run_root(cmd: str) -> str:
    """Run a shell command inside the container as root.

    For setup/teardown ops that need privileges the app user doesn't
    have — chmod on broker-owned files in /run/cvault, /etc/hosts edits,
    process signals to the supervisor. Use sparingly; tests that touch
    state managed by the app should prefer `container_exec` (runs as
    the app's uid) so the app can read/clean up afterwards.
    """
    result = subprocess.run(
        ["docker", "exec", "-u", "0", CONTAINER_NAME, "bash", "-c", cmd],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()
