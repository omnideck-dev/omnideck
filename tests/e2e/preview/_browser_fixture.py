"""Helpers for the browser-takeover e2e fixture page.

``fixtures/browser_fixture.html`` is pushed into the container home and served
back to the sandboxed Chrome by the app's container-file route. Each mode
renders one full-viewport target and signals back by *navigating* with a query
param — the only channel the host test can observe (it sees the screencast
image, never the remote DOM), which rides the nav push to the address bar.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.e2e._helpers import push_file_to_container
from tests.e2e._protocol import open_url

HOME = "/home/omnideck"
FIXTURE_NAME = "bfix.html"
FIXTURE_CONTAINER_PATH = f"{HOME}/{FIXTURE_NAME}"
_FIXTURE_HOST_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "browser_fixture.html"


def install_fixture() -> None:
    """Copy the fixture HTML into the container home (served by the app)."""
    push_file_to_container(str(_FIXTURE_HOST_PATH), FIXTURE_CONTAINER_PATH)


def base_url() -> str:
    return os.environ.get("OMNIDECK_URL", "http://localhost:8080")


def fixture_url(mode: str = "idle") -> str:
    """The URL the sandboxed Chrome opens to load the fixture in *mode*."""
    return f"{base_url()}{HOME}/{FIXTURE_NAME}?mode={mode}"


def open_fixture(mode: str = "idle") -> str:
    """Directive: agent opens the fixture in *mode* in a new tab."""
    return open_url(fixture_url(mode))
