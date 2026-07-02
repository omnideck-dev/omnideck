"""save_page_content writes the current page as markdown to the home dir."""

from __future__ import annotations

import pytest

from config import load_config
from tools.browser.core.exceptions import BrowserToolError
from tools.browser.save_content import save_page_content

_EXPECTED_MARKDOWN = """\
# The Hubble Telescope

Hubble has orbited Earth since 1990, returning deep-field images of distant galaxies.

## Instruments

It carries cameras and spectrographs. See the [mission overview](</article/article.html>) for details.

  * Wide Field Camera 3
  * Cosmic Origins Spectrograph"""


async def test_save_page_content_writes_markdown(browser_session, servers, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(load_config().virtual_computer, "home_dir", str(home))

    tab = await browser_session.open(f"{servers.primary}/article/article.html")
    result = await save_page_content("article.md", tab=tab)

    saved = home / "article.md"
    assert saved.exists()
    assert saved.read_text().strip() == _EXPECTED_MARKDOWN
    # The tool returns a "[Saved: <name> | <full path> | <size> bytes]" line.
    assert result == f"[Saved: article.md | {saved} | {saved.stat().st_size} bytes]"


async def test_save_page_content_rejects_paths(browser_session, servers, tmp_path, monkeypatch):
    monkeypatch.setattr(load_config().virtual_computer, "home_dir", str(tmp_path))
    tab = await browser_session.open(f"{servers.primary}/article/article.html")

    with pytest.raises(BrowserToolError):
        await save_page_content("sub/dir/page.md", tab=tab)
