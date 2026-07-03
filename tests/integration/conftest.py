"""Integration test fixtures.

These tests require a running container with Ollama available.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _require_running_container():
    """Skip integration tests unless OMNIDECK_URL is set."""
    if not os.environ.get("OMNIDECK_URL"):
        pytest.skip("OMNIDECK_URL not set — integration tests need a running container")
