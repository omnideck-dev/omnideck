"""Unit tests for the custom.css theme tools."""

from __future__ import annotations

import re
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.theme import ensure_custom_css_file, get_custom_css, set_custom_css
from tools.theme.theme import DEFAULT_CUSTOM_CSS

GLOBAL_CSS = Path(__file__).parents[3] / "server" / "ui" / "src" / "global.css"


@pytest.fixture(autouse=True)
def _tmp_css(tmp_path):
    """Point the custom.css path at a temp file."""
    path = tmp_path / "custom.css"
    with patch("tools.theme.theme.custom_css_path", return_value=path):
        yield path


def _dark_block_vars() -> set[str]:
    css = GLOBAL_CSS.read_text(encoding="utf-8")
    dark = css[css.index('[data-theme="dark"]'):]
    dark = dark[: dark.index("}")]
    return set(re.findall(r"(--[\w-]+)\s*:", dark))


@pytest.mark.unit
def test_ensure_seeds_default_when_missing(_tmp_css):
    ensure_custom_css_file()
    assert _tmp_css.read_text(encoding="utf-8") == DEFAULT_CUSTOM_CSS


@pytest.mark.unit
def test_ensure_does_not_overwrite_existing(_tmp_css):
    _tmp_css.write_text(".foo { color: red; }", encoding="utf-8")
    ensure_custom_css_file()
    assert _tmp_css.read_text(encoding="utf-8") == ".foo { color: red; }"


@pytest.mark.unit
def test_default_has_every_dark_varying_variable_commented_out():
    """Every var in global.css's dark block is listed, and nothing is active."""
    listed = set(re.findall(r"/\*\s*(--[\w-]+)\s*:", DEFAULT_CUSTOM_CSS))
    assert _dark_block_vars() <= listed
    # Strip comments: nothing but selectors and braces may remain.
    stripped = re.sub(r"/\*.*?\*/", "", DEFAULT_CUSTOM_CSS, flags=re.S)
    assert "--" not in stripped


@pytest.mark.unit
def test_default_includes_fonts_section_without_layout_tokens():
    for name in ("--font-body", "--font-code", "--font-brand"):
        assert f"/* {name}:" in DEFAULT_CUSTOM_CSS
    for prefix in ("--sp-", "--z-", "--radius-", "--ease", "--header-height"):
        assert prefix not in DEFAULT_CUSTOM_CSS


@pytest.mark.unit
def test_default_variables_exist_in_global_css():
    """Guards against the seeded file drifting from the real theme variables."""
    known = set(re.findall(r"(--[\w-]+)\s*:", GLOBAL_CSS.read_text(encoding="utf-8")))
    listed = set(re.findall(r"/\*\s*(--[\w-]+)\s*:", DEFAULT_CUSTOM_CSS))
    assert listed <= known


@pytest.mark.unit
async def test_get_seeds_and_returns_default(_tmp_css):
    result = await get_custom_css()
    assert result == {"status": "ok", "css": DEFAULT_CUSTOM_CSS}
    assert _tmp_css.exists()


@pytest.mark.unit
async def test_set_then_get_round_trips(_tmp_css):
    css = ":root { --accent: purple; }\n"
    result = await set_custom_css(css)
    assert result == {"status": "ok", "length": len(css)}
    assert (await get_custom_css())["css"] == css


@pytest.mark.unit
async def test_set_replaces_whole_file(_tmp_css):
    await set_custom_css("a { b: c }")
    await set_custom_css("d { e: f }")
    assert _tmp_css.read_text(encoding="utf-8") == "d { e: f }"


@pytest.mark.unit
async def test_set_leaves_no_temp_files(_tmp_css):
    await set_custom_css("x { y: z }")
    assert [p.name for p in _tmp_css.parent.iterdir()] == ["custom.css"]


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
async def test_written_file_stays_readable_by_humans(_tmp_css):
    """Temp files are owner-only; custom.css is hand-edited too, so it must not end up 0600."""
    await set_custom_css("x { y: z }")
    assert stat.S_IMODE(_tmp_css.stat().st_mode) == 0o644


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_seeded_file_stays_readable_by_humans(_tmp_css):
    ensure_custom_css_file()
    assert stat.S_IMODE(_tmp_css.stat().st_mode) == 0o644


@pytest.mark.unit
async def test_failed_replace_keeps_original_and_cleans_up(_tmp_css):
    _tmp_css.write_text("original", encoding="utf-8")
    with patch("pathlib.Path.replace", side_effect=OSError("boom")), pytest.raises(OSError):
        await set_custom_css("new")
    assert _tmp_css.read_text(encoding="utf-8") == "original"
    assert [p.name for p in _tmp_css.parent.iterdir()] == ["custom.css"]
