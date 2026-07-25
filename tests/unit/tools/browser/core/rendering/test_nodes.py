"""Tests for structured DOM nodes."""

import pytest

from tools.browser.core.rendering.nodes import (
    DomNode,
    NodeType,
    parse_nodes,
)


@pytest.mark.unit
class TestParseNodes:
    """Parsing raw JS dicts into DomNode instances."""

    def test_minimal_text_node(self):
        """A minimal text node with just type and depth."""
        raw = [{"type": "text", "depth": 0, "text": "Hello world"}]
        nodes = parse_nodes(raw)
        assert len(nodes) == 1
        n = nodes[0]
        assert n.type == NodeType.TEXT
        assert n.depth == 0
        assert n.text == "Hello world"

    def test_interactive_node_with_all_fields(self):
        """An interactive node populates all optional fields."""
        raw = [
            {
                "type": "interactive",
                "role": "button",
                "name": "Submit",
                "text": "",
                "value": "",
                "level": None,
                "depth": 3,
                "tag": "BUTTON",
                "expanded": None,
                "selected": None,
                "checked": None,
                "pressed": True,
            }
        ]
        nodes = parse_nodes(raw)
        assert len(nodes) == 1
        n = nodes[0]
        assert n.type == NodeType.INTERACTIVE
        assert n.role == "button"
        assert n.name == "Submit"
        assert n.pressed is True
        assert n.checked is None

    def test_heading_node(self):
        """A heading node preserves level."""
        raw = [{"type": "heading", "depth": 1, "name": "Section", "level": 2}]
        nodes = parse_nodes(raw)
        assert nodes[0].type == NodeType.HEADING
        assert nodes[0].level == 2
        assert nodes[0].name == "Section"

    def test_container_markers(self):
        """Container start/end markers are parsed correctly."""
        raw = [
            {"type": "container_start", "depth": 1, "tag": "TABLE"},
            {"type": "container_end", "depth": 1, "tag": "TABLE"},
        ]
        nodes = parse_nodes(raw)
        assert nodes[0].type == NodeType.CONTAINER_START
        assert nodes[1].type == NodeType.CONTAINER_END

    def test_defaults_for_missing_fields(self):
        """Missing optional fields get sensible defaults."""
        raw = [{"type": "text", "depth": 2}]
        nodes = parse_nodes(raw)
        n = nodes[0]
        assert n.role is None
        assert n.name is None
        assert n.text is None
        assert n.value is None

    def test_empty_list(self):
        """Empty input returns empty list."""
        assert parse_nodes([]) == []

    def test_multiple_nodes(self):
        """Multiple nodes parsed in order."""
        raw = [
            {"type": "heading", "depth": 0, "name": "Title", "level": 1},
            {"type": "text", "depth": 1, "text": "Body text"},
            {"type": "interactive", "depth": 1, "role": "link", "name": "Click"},
        ]
        nodes = parse_nodes(raw)
        assert len(nodes) == 3
        assert [n.type for n in nodes] == [
            NodeType.HEADING,
            NodeType.TEXT,
            NodeType.INTERACTIVE,
        ]
