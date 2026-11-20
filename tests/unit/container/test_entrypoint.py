"""Exercise service shutdown without running container setup or host services."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("exit_source", ["broker", "omnideck", "sigterm"])
def test_production_shutdown_terminates_all_background_jobs(tmp_path, exit_source):
    mock_service = tmp_path / "service.py"
    mock_service.write_text(
        """
import os
from pathlib import Path
import signal
import sys
import time

directory = Path(os.environ["MOCK_STATE"])
name = sys.argv[1]

def stop(signum, frame):
    (directory / (name + ".stopped")).touch()
    sys.exit(0)

signal.signal(signal.SIGTERM, stop)
(directory / (name + ".ready")).touch()
while True:
    if (directory / (name + ".fail")).exists():
        sys.exit(7)
    time.sleep(0.01)
"""
    )
    gosu = tmp_path / "gosu"
    gosu.write_text('#!/bin/sh\nexec "$MOCK_PYTHON" "$MOCK_SERVICE" "$1"\n')
    gosu.chmod(0o755)

    # Execute the production lifecycle section verbatim. Earlier setup changes
    # container-owned paths and requires services that this isolated test mocks.
    entrypoint = (ROOT / "container/entrypoint.sh").read_text()
    setup, separator, lifecycle = entrypoint.partition("cd /opt/omnideck\n")
    assert separator and "Xvfb" in setup
    script = '"$MOCK_PYTHON" "$MOCK_SERVICE" xvfb &\n' + lifecycle
    process = subprocess.Popen(
        ["/bin/bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DEV_MODE": "false",
            "MOCK_PYTHON": sys.executable,
            "MOCK_SERVICE": str(mock_service),
            "MOCK_STATE": str(tmp_path),
        },
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        names = ("broker", "omnideck", "xvfb")
        deadline = time.monotonic() + 5
        while not all((tmp_path / f"{name}.ready").exists() for name in names):
            assert process.poll() is None, "Entrypoint exited before services started"
            assert time.monotonic() < deadline, "Mock services failed to start"
            time.sleep(0.01)

        if exit_source == "sigterm":
            process.terminate()
        else:
            (tmp_path / f"{exit_source}.fail").touch()

        try:
            status = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pytest.fail("Entrypoint hung while shutting down its background jobs")
        if exit_source != "sigterm":
            assert status == 7, "Service failure status must reach the container runtime"
        for name in names:
            if name != exit_source:
                assert (tmp_path / f"{name}.stopped").exists(), f"{name} missed SIGTERM"
    finally:
        # Only this test's private process group is eligible for cleanup.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
