"""Tests for the composer slug of a skill name."""

import json
from pathlib import Path

import pytest

from agent_core.skills import skill_slug

pytestmark = [pytest.mark.unit]

# Shared with the composer's client-side slug, so the two stay identical.
_SHARED = json.loads((Path(__file__).parents[3] / "fixtures" / "composer_skill_matching.json").read_text())


@pytest.mark.parametrize(("name", "slug"), _SHARED["slugs"])
def test_skill_slug(name, slug):
    assert skill_slug(name) == slug
