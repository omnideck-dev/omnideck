"""Tests for server._tool_category_routes.

GET /api/tool-categories serializes the gated catalog: id, label, description,
the tool names each grants, and per-integration connection state (null for a
static category).
"""

import json
from unittest.mock import MagicMock

import pytest

from sdk.skills import ToolCategory
from server._tool_category_routes import handle_list_tool_categories


def _tool(name):
    def f():
        ...

    f.__name__ = name
    return f


@pytest.fixture(autouse=True)
def _catalog(monkeypatch):
    """A fixed catalog: one static category, one connected and one disconnected
    integration category."""

    async def _cats():
        return {
            "coding": ToolCategory("coding", "Coding", "Write code.", [_tool("read_file"), _tool("run_bash_cmd")]),
            "email": ToolCategory("email", "Email", "Read mail.", [_tool("search_email")], connected=True),
            "calendar": ToolCategory("calendar", "Calendar", "Events.", [], connected=False),
        }

    monkeypatch.setattr("server._tool_category_routes.tool_categories", _cats)


@pytest.mark.unit
async def test_lists_all_tool_categories():
    resp = await handle_list_tool_categories(MagicMock())
    body = json.loads(resp.body)
    assert {c["id"] for c in body} == {"coding", "email", "calendar"}


@pytest.mark.unit
async def test_serializes_metadata_and_tool_names():
    body = json.loads((await handle_list_tool_categories(MagicMock())).body)
    coding = next(c for c in body if c["id"] == "coding")
    assert coding["label"] == "Coding"
    assert coding["description"] == "Write code."
    assert coding["tool_count"] == 2
    assert set(coding["tools"]) == {"read_file", "run_bash_cmd"}


@pytest.mark.unit
async def test_static_category_connected_is_null():
    body = json.loads((await handle_list_tool_categories(MagicMock())).body)
    coding = next(c for c in body if c["id"] == "coding")
    assert coding["connected"] is None


@pytest.mark.unit
async def test_integration_connection_state_reported():
    body = json.loads((await handle_list_tool_categories(MagicMock())).body)
    by_id = {c["id"]: c for c in body}
    assert by_id["email"]["connected"] is True
    assert by_id["calendar"]["connected"] is False
    assert by_id["calendar"]["tool_count"] == 0
