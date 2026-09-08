"""Agent-facing file discovery and text search backed by bounded ripgrep."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Literal

_SEARCH_TIMEOUT_SECONDS = 10.0
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_RECORD_BYTES = 1024 * 1024
_MAX_LINE_CHARS = 4096
_Mode = Literal["matches", "files", "count"]


class _OutputLimit(Exception):
    """A single ripgrep record exceeded the bounded transport buffer."""


def _label(value: str) -> str:
    """Keep unusual filenames unambiguous in otherwise plain-text output."""
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        return json.dumps(value, ensure_ascii=True)
    return value


def _rg_text(value: dict[str, Any]) -> str:
    if "text" in value:
        return str(value["text"])
    return base64.b64decode(value["bytes"]).decode("utf-8", errors="replace")


@dataclass
class _SearchResult:
    """Bounded collected rows plus completeness metadata for text rendering."""

    root: Path
    mode: _Mode
    rows: list[str] = field(default_factory=list)
    count: int = 0
    size: int = 0
    reason: str | None = None
    error: str | None = None
    excerpts: bool = False

    def add(self, row: str, *, counted: bool, limit: int) -> bool:
        if counted and self.count >= limit:
            self.reason = "result_limit; narrow the path or file pattern to see remaining results"
            return False
        size = len(row.encode("utf-8", errors="backslashreplace")) + 1
        if self.size + size > _MAX_OUTPUT_BYTES:
            self.reason = "output_limit; narrow the search or request less context"
            return False
        self.rows.append(row)
        self.size += size
        self.count += int(counted)
        return True

    def render(self) -> str:
        unit = {"matches": "matching lines", "files": "files", "count": "per-file counts of matching lines"}[self.mode]
        if self.error:
            status = f"Search incomplete: error. {self.error}"
        elif self.reason:
            status = f"Search incomplete: {self.reason}."
        else:
            status = "Search complete."
        excerpt = "\nLong lines are excerpts; inspect file sections for the full text." if self.excerpts else ""
        return f"Root: {_label(str(self.root))}\nReturned {self.count} {unit}. {status}{excerpt}\n\n" + "\n".join(self.rows)


def _scope(path: str, include: list[str] | None, exclude: list[str] | None) -> tuple[Path, list[str]]:
    root = Path(path).absolute()
    args = ["rg", "--no-config", "--engine=default", "--hidden", "--no-ignore", "--color=never", "--threads=1", "--line-buffered", "--crlf"]
    # Retain the previous root-relative glob scope, including dotfiles and
    # ignored files. Explicit file searches historically bypassed glob filters.
    if not root.is_file():
        for pattern in include or []:
            glob = _glob(pattern)
            args += ["--glob", glob, "--glob", glob.rstrip("/") + "/**"]
        for pattern in (exclude or []) + [".git/**", "node_modules/**", "__pycache__/**", "**/*.lock"]:
            glob = _glob(pattern)
            args += ["--glob", "!" + glob, "--glob", "!" + glob.rstrip("/") + "/**"]
    return root, args


def _glob(pattern: str) -> str:
    if not pattern or pattern.startswith(("/", "!")) or len(pattern) > 4096:
        raise ValueError("Use nonempty root-relative globs of at most 4096 characters; put exclusions in exclude_globs.")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    return "/" + pattern


async def _error_text(reader: asyncio.StreamReader) -> str:
    saved = bytearray()
    while chunk := await reader.read(4096):
        saved.extend(chunk[:max(0, 4096 - len(saved))])
    return saved.decode("utf-8", errors="replace").strip()


async def _records(reader: asyncio.StreamReader, mode: _Mode) -> AsyncIterator[tuple[bytes | None, bytes]]:
    """Frame JSON lines, NUL paths, or NUL-path/newline-count pairs incrementally."""
    buffer = bytearray()
    count_path: bytes | None = None
    while chunk := await reader.read(4096):
        buffer.extend(chunk)
        while True:
            delimiter = b"\n" if mode == "matches" or (mode == "count" and count_path is not None) else b"\0"
            boundary = buffer.find(delimiter)
            if boundary < 0:
                if len(buffer) > _MAX_RECORD_BYTES:
                    raise _OutputLimit
                break
            if boundary > _MAX_RECORD_BYTES:
                raise _OutputLimit
            record = bytes(buffer[:boundary])
            del buffer[:boundary + 1]
            if mode == "count" and count_path is None:
                count_path = record
            else:
                yield count_path, record
                count_path = None
    if buffer or count_path is not None:
        raise ValueError("Search ended with an incomplete result record; retry with a narrower path.")


async def _run(args: list[str], root: Path, mode: _Mode, limit: int) -> str:
    result = _SearchResult(root, mode)
    if not root.exists():
        result.error = "Path not found. Choose an existing file or directory."
        return result.render()
    cwd = root.parent if root.is_file() else root
    args += ["--", root.name if root.is_file() else "."]
    try:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        result.error = f"Could not start ripgrep: {exc}."
        return result.render()
    assert process.stdout is not None and process.stderr is not None
    stderr = asyncio.create_task(_error_text(process.stderr))
    try:
        async with asyncio.timeout(_SEARCH_TIMEOUT_SECONDS):
            async for count_path, record in _records(process.stdout, mode):
                if mode == "matches":
                    event = json.loads(record)
                    if event["type"] not in ("match", "context"):
                        continue
                    data = event["data"]
                    name = _rg_text(data["path"]).removeprefix("./")
                    text = _rg_text(data["lines"]).rstrip("\r\n")
                    counted = event["type"] == "match"
                    if len(text) > _MAX_LINE_CHARS:
                        start = data.get("submatches", [{}])[0].get("start", 0) if counted else 0
                        char_start = len(text.encode("utf-8")[:start].decode("utf-8", errors="ignore"))
                        offset = max(0, char_start - _MAX_LINE_CHARS // 2)
                        text = "[excerpt] " + text[offset:offset + _MAX_LINE_CHARS]
                        result.excerpts = True
                    marker = ":" if counted else "-"
                    row = f"{_label(name)}{marker}{data['line_number']}{marker} {text}"
                else:
                    name = os.fsdecode(count_path if count_path is not None else record).removeprefix("./")
                    row = _label(name) + (f": {int(record)}" if mode == "count" else "")
                    counted = True
                if not result.add(row, counted=counted, limit=limit):
                    break
            if result.reason is None:
                code = await process.wait()
                detail = await stderr
                if code not in (0, 1):
                    result.error = detail or f"ripgrep exited with status {code}"
                    result.error = "\n".join(
                        line for line in result.error.splitlines() if "PCRE2" not in line and "--pcre2" not in line
                    )
                    result.error += (
                        "\nCheck the path/globs or simplify the regex; regex=false searches literal text. "
                        "This tool does not support lookaround or backreferences."
                    )
    except TimeoutError:
        result.reason = f"timeout after {_SEARCH_TIMEOUT_SECONDS:g} seconds; narrow the path or pattern"
    except _OutputLimit:
        result.reason = "output_limit; a result line was too large, use files/count output or a narrower search"
    except (ValueError, KeyError) as exc:
        result.error = str(exc)
    finally:
        if process.returncode is None:
            process.kill()
        # Drain after killing: waiting with a full pipe can otherwise deadlock.
        await process.stdout.read()
        await process.wait()
        await stderr
    return result.render()


def _validate(pattern: str, limit: int) -> None:
    if len(pattern) > 4096 or not 1 <= limit <= 10_000:
        raise ValueError("Use a pattern of at most 4096 characters and max_results from 1 to 10000.")


async def find_files(
    pattern: str,
    path: str = ".",
    *,
    exclude_globs: list[str] | None = None,
    max_results: int = 100,
) -> str:
    """Find files by root-relative path glob, not by their contents.

    Use **/*runner*.py to find runner filenames at any depth, or *.py for
    files directly in the root. Hidden and gitignored files are included;
    root .git, node_modules, __pycache__, and lock files are excluded.
    Returns paths as text, with explicit incomplete-result and error notices.

    Args:
        pattern: Root-relative filename/path glob, such as **/*.py.
        path: Directory to search; defaults to the current working directory, reported in the result.
        exclude_globs: Additional root-relative exclusion globs.
        max_results: Maximum returned filenames, from 1 to 10000; defaults to 100.
    """
    try:
        _validate(pattern, max_results)
        root, args = _scope(path, [pattern], exclude_globs)
        if not root.is_dir():
            return "Search error: find_files requires an existing directory."
        return await _run(args + ["--files", "--null"], root, "files", max_results)
    except ValueError as exc:
        return f"Search error: {exc}"


async def search_text(
    pattern: str,
    path: str = ".",
    *,
    regex: bool = True,
    case_sensitive: bool = False,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    output: Literal["matches", "files", "count"] = "matches",
    context: int = 2,
    max_results: int = 100,
) -> str:
    """Search file contents, returning matching lines, filenames, or per-file counts.

    Defaults to case-insensitive regex matching with two surrounding lines.
    Use regex=false for literal text. Lookaround and backreferences are not
    supported; no backtracking-engine fallback is enabled. Hidden/gitignored
    files are searched, with the same exclusions as find_files. Explicit file
    paths bypass glob filters. Counts count matching lines, not occurrences.
    Search has a ten-second deadline and bounded output; incomplete results
    are labeled. Large returned output may be saved temporarily by the runtime.

    Args:
        pattern: Text or regex to match inside files, up to 4096 characters.
        path: File or directory to search; defaults to the current working directory, reported in the result.
        regex: Interpret pattern as regex (default true); false searches literal text.
        case_sensitive: Match exact letter case when true; defaults to false.
        include_globs: Optional root-relative file globs, such as src/**/*.py.
        exclude_globs: Additional root-relative exclusion globs.
        output: matches for matching lines, files for matching filenames, count for matching-line counts per file.
        context: Surrounding lines per match, from 0 to 100; defaults to 2. Only used for matches output.
        max_results: Maximum matching lines, filenames, or per-file count rows, from 1 to 10000; defaults to 100.
    """
    try:
        _validate(pattern, max_results)
        if output not in ("matches", "files", "count") or not 0 <= context <= 100:
            raise ValueError("Use output=matches/files/count and context from 0 to 100.")
        root, args = _scope(path, include_globs, exclude_globs)
        args += ["--case-sensitive" if case_sensitive else "--ignore-case"]
        if not regex:
            args += ["--fixed-strings"]
        if output == "matches":
            args += ["--json", "--context", str(context)]
        elif output == "files":
            args += ["--files-with-matches", "--null"]
        else:
            args += ["--count", "--null", "--with-filename"]
        args += ["--regexp", pattern]
        return await _run(args, root, output, max_results)
    except ValueError as exc:
        return f"Search error: {exc}"
