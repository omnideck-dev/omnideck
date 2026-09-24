"""Integration test fixtures."""

import os

import pytest


@pytest.fixture
def omnideck_url() -> str:
    """Opt-in fixture for tests that require a separately running app."""
    value = os.environ.get("OMNIDECK_URL")
    if not value:
        pytest.skip("OMNIDECK_URL not set")
    return value
