"""Real ripgrep contract tests for agent search scope, formats, and limits."""

import pytest

from tools.virtual_computer import find_files, search_text


@pytest.mark.parametrize("tool", [find_files, search_text])
def test_ollama_sdk_can_serialize_search_tools(tool):
    """Exercise the real SDK conversion used after loading the coder skill."""
    from ollama._utils import convert_function_to_tool

    schema = convert_function_to_tool(tool).model_dump()
    assert schema["function"]["name"] == tool.__name__
    properties = schema["function"]["parameters"]["properties"]
    assert properties["pattern"]["type"] == "string"
    assert properties["max_results"]["type"] == "integer"
    if tool is search_text:
        assert properties["output"]["type"] == "string"
        assert properties["regex"]["type"] == "boolean"


@pytest.fixture
def tree(tmp_path):
    files = {
        "root.py": "before\nHello needle\nafter\n",
        "src/app.py": "hello NEEDLE\nhello again\n",
        "src/inner/leaf.py": "hello needle\n",
        "src/readme.md": "hello markdown\n",
        ".hidden": "hello hidden\n",
        "ignored.txt": "hello ignored\n",
        ".gitignore": "ignored.txt\n",
        ".git/config": "hello excluded\n",
        "node_modules/pkg/index.js": "hello excluded\n",
        "__pycache__/cache.py": "hello excluded\n",
        "package.lock": "hello excluded\n",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


async def test_defaults_include_context_regex_and_case_insensitive_matches(tree):
    result = await search_text("hello|missing", str(tree / "root.py"))
    assert "root.py:2: Hello needle" in result
    assert "root.py-1- before" in result and "root.py-3- after" in result
    assert "Search complete" in result
    assert "Returned 1 matching lines" in result


async def test_literal_case_and_anchors(tree):
    assert "Returned 0 matching lines" in await search_text("hello", str(tree / "root.py"), case_sensitive=True)
    assert "Returned 0 matching lines" in await search_text("hello|missing", str(tree), regex=False)
    assert "root.py:2:" in await search_text("^Hello needle$", str(tree), case_sensitive=True)


@pytest.mark.parametrize("pattern,expected", [
    ("*.py", {"root.py"}),
    ("**/*.py", {"root.py", "src/app.py", "src/inner/leaf.py"}),
    ("src/*.py", {"src/app.py"}),
    ("src/**/*.py", {"src/app.py", "src/inner/leaf.py"}),
])
async def test_root_relative_globs_for_both_tools(tree, pattern, expected):
    found = await find_files(pattern, str(tree))
    searched = await search_text("hello", str(tree), include_globs=[pattern], output="files")
    assert set(found.split("\n\n", 1)[1].splitlines()) == expected
    assert set(searched.split("\n\n", 1)[1].splitlines()) == expected


async def test_scope_includes_hidden_and_ignored_but_keeps_default_exclusions(tree):
    result = await search_text("hello", str(tree), output="files")
    assert ".hidden" in result and "ignored.txt" in result
    for name in (".git/config", "node_modules", "__pycache__", "package.lock"):
        assert name not in result
    found = await find_files("**/*", str(tree))
    assert ".hidden" in found and "ignored.txt" in found
    assert ".git/config" not in found and "package.lock" not in found


async def test_excludes_win_and_explicit_files_bypass_globs(tree):
    result = await search_text("hello", str(tree), include_globs=["**/*.py"], exclude_globs=["src/**"], output="files")
    assert result.split("\n\n", 1)[1] == "root.py"
    result = await search_text("hello", str(tree / "package.lock"), exclude_globs=["**/*"])
    assert "package.lock:1:" in result


async def test_empty_globs_do_not_filter(tree):
    assert await search_text("hello", str(tree), include_globs=[], exclude_globs=[]) == await search_text("hello", str(tree))


async def test_counts_are_matching_lines_and_filenames_are_not_content_search(tree):
    result = await search_text("hello", str(tree), output="count", include_globs=["src/**/*.py"])
    assert "src/app.py: 2" in result and "src/inner/leaf.py: 1" in result
    assert "Returned 0 files" in await find_files("**/*needle*", str(tree))
    assert "Returned 3 files" in await search_text("needle", str(tree), output="files")


@pytest.mark.parametrize("output", ["matches", "files", "count"])
async def test_limits_and_exact_limit_completeness(tree, output):
    result = await search_text("hello", str(tree), output=output, max_results=1, context=0)
    assert "Search incomplete: result_limit" in result
    result = await search_text("hello", str(tree / "root.py"), output=output, max_results=1)
    assert "Search complete" in result
    assert "result_limit" in await find_files("**/*", str(tree), max_results=1)


async def test_context_30_is_supported_and_counted_separately(tmp_path):
    source = tmp_path / "context.txt"
    source.write_text("\n".join([f"before{i}" for i in range(30)] + ["needle"] + [f"after{i}" for i in range(30)]))
    result = await search_text("needle", str(source), context=30, max_results=1)
    assert "before0" in result and "after29" in result
    assert "Returned 1 matching lines. Search complete" in result


@pytest.mark.parametrize("pattern", ["[", "(?<=hello)needle", r"(hello)\1"])
async def test_invalid_or_unsupported_regex_is_actionable(tree, pattern):
    result = await search_text(pattern, str(tree))
    assert "Search incomplete: error" in result and "regex=false" in result


async def test_missing_path_and_no_matches_are_distinct(tree):
    assert "Path not found" in await search_text("hello", str(tree / "missing"))
    assert "Returned 0 matching lines. Search complete" in await search_text("not-found", str(tree))


async def test_large_file_can_be_searched_beyond_old_prefix_limit(tmp_path):
    source = tmp_path / "large.txt"
    source.write_text("x" * (9 * 1024 * 1024) + "\nlate-needle\n")
    result = await search_text("late-needle", str(source), context=0)
    assert "large.txt:2: late-needle" in result and "Search complete" in result


async def test_large_lines_and_accumulation_are_bounded(tmp_path, monkeypatch):
    from tools.virtual_computer import search_ops
    source = tmp_path / "large.txt"
    source.write_text("needle " + "x" * (2 * 1024 * 1024))
    result = await search_text("needle", str(source))
    assert len(result) < 1000 and "output_limit" in result
    source.write_text(("needle " + "x" * 1000 + "\n") * 200)
    monkeypatch.setattr(search_ops, "_MAX_OUTPUT_BYTES", 4000)
    result = await search_text("needle", str(source), max_results=10000)
    assert len(result.encode()) < 4500 and "output_limit" in result


async def test_long_line_excerpt_contains_late_match_and_preserves_normal_lines(tmp_path):
    source = tmp_path / "lines.txt"
    source.write_text("x" * 3000 + "needle\n" + "y" * 10000 + "needle\n")
    result = await search_text("needle", str(source), context=0)
    assert "lines.txt:1: " + "x" * 3000 + "needle" in result
    assert "lines.txt:2: [excerpt]" in result and result.count("needle") == 2


@pytest.mark.parametrize("mode", ["matches", "files", "count"])
async def test_unusual_filenames_and_option_like_patterns(tmp_path, mode):
    source = tmp_path / "a\nb:c.txt"
    source.write_text("--needle\n")
    result = await search_text("--needle", str(tmp_path), output=mode, regex=False)
    assert '"a\\nb:c.txt"' in result and "Search complete" in result
    assert '"a\\nb:c.txt"' in await find_files("**/*.txt", str(tmp_path))


async def test_directory_glob_and_crlf_anchors(tree):
    assert "src/app.py" in await find_files("src", str(tree))
    assert "root.py" not in (await search_text("hello", str(tree), include_globs=["src"], output="files")).split("\n\n", 1)[1]
    (tree / "windows.txt").write_bytes(b"before\r\nhello\r\nafter\r\n")
    result = await search_text("^hello$", str(tree / "windows.txt"))
    assert "windows.txt:2: hello" in result and "Search complete" in result


async def test_user_ripgrep_config_cannot_override_engine_or_scope(tree, tmp_path, monkeypatch):
    config = tmp_path / "rg-config"
    config.write_text("--pcre2\n--glob=!*.py\n")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(config))
    assert "root.py" in await find_files("**/*.py", str(tree))
    assert "Search incomplete: error" in await search_text("(?<=hello) needle", str(tree))
