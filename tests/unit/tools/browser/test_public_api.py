"""Contract tests for the browser tools exposed to agents."""

from __future__ import annotations

import inspect

import pytest

from tools.browser import (
    browse_page,
    browser_visual_action,
    click,
    close_tab,
    drag,
    execute_javascript,
    fill_field,
    go_back,
    goto,
    inspect_page,
    new_tab,
    press_and_hold,
    press_keys,
    read_page,
    save_page_content,
    scroll_page,
    select_option,
)

_TOOL_SIGNATURES = {
    browse_page: "(scope: 'str | None' = None, full_page: 'bool' = False, *, tab: 'str') -> 'str'",
    browser_visual_action: "(task: 'str', *, tab: 'str') -> 'str'",
    click: "(ref: 'str', *, tab: 'str') -> 'str'",
    close_tab: "(*, tab: 'str') -> 'str'",
    drag: "(source: 'str', target: 'str', *, tab: 'str') -> 'str'",
    execute_javascript: "(code: 'str', timeout_ms: 'int' = 10000, *, tab: 'str') -> 'str'",
    fill_field: "(ref: 'str', value: 'str | int | float | bool | None', *, tab: 'str') -> 'str'",
    go_back: "(*, tab: 'str') -> 'str'",
    goto: "(url: 'str', *, tab: 'str') -> 'str'",
    inspect_page: "(prompt: 'str', *, mode: 'str' = 'full_page', ref: 'str | None' = None, tab: 'str') -> 'str'",
    new_tab: "(url: 'str') -> 'str'",
    press_and_hold: "(ref: 'str', duration_ms: 'int' = 3000, *, tab: 'str') -> 'str'",
    press_keys: "(keys: 'list[str]', *, tab: 'str') -> 'str'",
    read_page: "(chunk: 'int' = 1, query: 'str | None' = None, *, tab: 'str') -> 'str'",
    save_page_content: "(filename: 'str', *, tab: 'str') -> 'str'",
    scroll_page: "(direction: 'str' = 'down', amount: 'int | None' = None, *, tab: 'str') -> 'str'",
    select_option: "(ref: 'str', value: 'str', wait_after_select_ms: 'int | None' = None, *, tab: 'str') -> 'str'",
}


@pytest.mark.unit
@pytest.mark.parametrize(("tool", "expected"), _TOOL_SIGNATURES.items())
def test_agent_tool_signature_is_pinned(tool, expected: str) -> None:
    """Pin each intentional agent-tool signature."""
    assert str(inspect.signature(tool, follow_wrapped=True)) == expected


@pytest.mark.unit
@pytest.mark.parametrize("tool", _TOOL_SIGNATURES)
def test_agent_tool_has_google_style_docstring(tool) -> None:
    """Require complete Google-style documentation on every browser tool."""
    docstring = inspect.getdoc(tool)
    assert docstring is not None
    assert "Args:" in docstring
    assert "Returns:" in docstring
    assert "Raises:" in docstring

    parameters = inspect.signature(tool, follow_wrapped=True).parameters
    args_section = docstring.split("Args:", 1)[1].split("Returns:", 1)[0]
    for name in parameters:
        assert f"{name}:" in args_section
