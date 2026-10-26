"""Each Markdown conversion owns its parser state."""

from browser.core.markdown import html_to_markdown


def test_abbreviation_definitions_do_not_leak_between_documents():
    first = html_to_markdown('<p><abbr title="First definition">API</abbr></p>')
    assert 'First definition' in first
    assert 'First definition' not in html_to_markdown('<p>Unrelated page</p>')
    second = html_to_markdown('<p><abbr title="Second definition">API</abbr></p>')
    assert 'Second definition' in second
    assert 'First definition' not in second
