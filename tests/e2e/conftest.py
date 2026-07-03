"""Root conftest for the e2e suite.

Keeps only what pytest needs to discover here. Generic infrastructure
helpers live in `tests/e2e/_helpers.py`; the wizard auto-setup lives in
`tests/e2e/_setup.py` and is registered via the pytest_plugins hook below.
"""

import os

import pytest

BASE_URL = os.environ.get("OMNIDECK_URL", "http://localhost:8080")

# Auto-completes the setup wizard before any test runs. Lives in a
# sibling module so the autouse fixture's implementation isn't crammed
# into the root conftest.
pytest_plugins = ["tests.e2e._setup"]


# Fail fast while iterating. Playwright defaults to 30s for actions like
# click/scroll_into_view; with the in-process fake there's no model latency, so
# a locator that never resolves means a real failure — surface it in seconds
# instead of hanging. Tests that need longer pass an explicit timeout.
DEFAULT_TIMEOUT_MS = 5_000


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure the browser context for all e2e tests."""
    return {
        "base_url": BASE_URL,
        "extra_http_headers": {"X-Requested-With": "XMLHttpRequest"},
    }


@pytest.fixture(autouse=True)
def _fast_action_timeout(page):
    """Lower the default action timeout for tests using the standard page."""
    page.set_default_timeout(DEFAULT_TIMEOUT_MS)
