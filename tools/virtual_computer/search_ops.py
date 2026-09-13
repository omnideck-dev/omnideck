"""Search operations: grep across files in the current workspace.

Skips binary files; returns structured matches suitable for LLM consumption.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

from ._fs_internal import is_binary_file
from .models import GrepMatch, GrepResult

logger = logging.getLogger(__name__)


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _expand_globstar_zero_depth(pattern: str) -> set[str]:
    """Expand a pattern so that each "**/" can also be zero directories.

    Example: "src/**/*.js" -> {"src/**/*.js", "src/*.js"}
    Works for multiple occurrences by generating all combinations.
    """
    pat = pattern.replace("\\", "/")
    token = "**/"
    if token not in pat:
        return {pat}
    parts = pat.split(token)
    # Reconstruct with either token kept or removed at each junction
    variants: set[str] = set()
    n = len(parts) - 1
    # Each bit in mask: 1 means keep token, 0 means drop
    for mask in range(1 << n):
        s = parts[0]
        for i in range(n):
            s += (token if (mask & (1 << i)) else "") + parts[i + 1]
        variants.add(s)
    return variants


def _apply_globs(
    paths: Iterable[Path],
    root: Path,
    include: list[str] | None,
    exclude: list[str] | None,
) -> Iterable[Path]:
    """Filter paths by include/exclude patterns using Path.glob (globstar-on).

    We expand include and exclude patterns using ``root.glob`` which supports
    ``**`` for recursive matches. Only files are considered.
    """
    # Build sets of included/excluded file Paths for fast membership checks
    included: set[Path] | None = None
    excluded: set[Path] = set()

    if include:
        inc_set: set[Path] = set()
        for pat in include:
            for expanded in _expand_globstar_zero_depth(pat):
                for gp in root.glob(expanded):
                    if gp.is_file():
                        inc_set.add(gp)
                    elif gp.is_dir():
                        for fp in gp.rglob("*"):
                            if fp.is_file():
                                inc_set.add(fp)
        included = inc_set

    if exclude:
        for pat in exclude:
            for expanded in _expand_globstar_zero_depth(pat):
                for gp in root.glob(expanded):
                    if gp.is_file():
                        excluded.add(gp)
                    elif gp.is_dir():
                        for fp in gp.rglob("*"):
                            if fp.is_file():
                                excluded.add(fp)

    for p in paths:
        if included is not None and p not in included:
            continue
        if p in excluded:
            continue
        yield p


def _search(
    pattern: str,
    *,
    path: str = ".",
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    regex: bool = True,
    case_sensitive: bool = False,
    context: int = 2,
    max_results: int | None = 1000,
    on_match: Callable[[GrepMatch], None] | None = None,
) -> GrepResult:
    """Collect bounded matches inside the disposable search process."""
    try:
        # Default excludes that are always applied (globstar semantics)
        default_excludes = [
            ".git/**",
            "node_modules/**",
            "__pycache__/**",
            "**/*.lock",
        ]
        # Merge default excludes with user-provided excludes
        exclude_globs = default_excludes if exclude_globs is None else exclude_globs + default_excludes

        # Resolve the search root (file or directory)
        root_abs = Path(path)
        if not root_abs.exists():
            return GrepResult(
                success=False,
                matches=[],
                truncated=False,
                searched_files=0,
                error="path not found",
            )

        flags = 0
        if not case_sensitive:
            flags |= re.IGNORECASE
        patt = re.compile(pattern if regex else re.escape(pattern), flags)
        ctx = max(0, context)
        max_results = min(max_results or 10_000, 10_000)
        output_bytes = 0
        incomplete = False

        matches: list[GrepMatch] = []
        searched = 0

        # Single file: search it directly, skip glob filtering
        file_iter: Iterable[Path]
        if root_abs.is_file():
            file_iter = iter([root_abs])
        else:
            file_iter = _apply_globs(_iter_files(root_abs), root_abs, include_globs, exclude_globs)

        for fpath in file_iter:
            try:
                if is_binary_file(fpath):
                    continue
                with fpath.open("rb") as source:
                    raw = source.read(_MAX_FILE_BYTES + 1)
                if len(raw) > _MAX_FILE_BYTES:
                    incomplete = True
                prefix = raw[:_MAX_FILE_BYTES]
                if len(raw) > _MAX_FILE_BYTES:
                    # Do not fabricate an end-of-line at the byte boundary:
                    # anchored patterns must only see complete source lines.
                    prefix = prefix[:prefix.rfind(b"\n") + 1]
                text = prefix.decode("utf-8", errors="replace")
            except OSError:  # pragma: no cover - defensive
                logger.warning("Skipping unreadable file %s", fpath)
                continue
            searched += 1
            all_lines = text.splitlines(keepends=False)
            file_display = str(fpath)
            for i, line in enumerate(all_lines):
                found = patt.search(line)
                if found:
                    # Preserve a useful excerpt around the match, not just a
                    # prefix that may omit the matched text entirely.
                    offset = max(0, found.start() - _MAX_LINE_CHARS // 2) if len(line) > _MAX_LINE_CHARS else 0
                    excerpt = line[offset:offset + _MAX_LINE_CHARS]
                    before = all_lines[max(0, i - ctx):i] if ctx > 0 else None
                    after = all_lines[i + 1:i + 1 + ctx] if ctx > 0 else None
                    clipped = len(line) > _MAX_LINE_CHARS or any(
                        len(value) > _MAX_LINE_CHARS for value in (before or []) + (after or [])
                    )
                    incomplete = incomplete or clipped
                    match = GrepMatch(
                        file_path=file_display, line_number=i + 1,
                        line=("[excerpt] " if offset else "") + excerpt,
                        context_before=[v[:_MAX_LINE_CHARS] for v in before] if before is not None else None,
                        context_after=[v[:_MAX_LINE_CHARS] for v in after] if after is not None else None,
                    )
                    size = len(match.model_dump_json().encode("utf-8")) + 32
                    if output_bytes + size > _MAX_OUTPUT_BYTES:
                        return GrepResult(
                            success=True, matches=matches, truncated=True, searched_files=searched,
                            notice="Search output limit reached. Narrow the path/pattern or request less context.",
                        )
                    output_bytes += size
                    matches.append(match)
                    if on_match is not None:
                        on_match(match)
                    if max_results is not None and len(matches) >= max_results:
                        return GrepResult(
                            success=True,
                            matches=matches,
                            truncated=True,
                            searched_files=searched,
                            notice="Match limit reached. Narrow the search to see remaining matches.",
                        )

        return GrepResult(
            success=True, matches=matches, truncated=incomplete, searched_files=searched,
            notice=("Search incomplete: large files were searched only through the first 8 MiB; "
                    "long matching/context lines may be excerpts. Narrow the search or inspect file sections."
                    if incomplete else None),
        )
    except re.error as exc:
        return GrepResult(success=False, matches=[], error=f"Invalid regex: {exc}. Correct the pattern or use regex=false.")
    except OSError:  # pragma: no cover - defensive
        logger.exception("grep failed")
        return GrepResult(
            success=False,
            matches=[],
            truncated=False,
            searched_files=0,
            error="grep failed",
        )


_SEARCH_TIMEOUT_SECONDS = 10.0
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_LINE_CHARS = 4096


async def grep(
    pattern: str,
    *,
    path: str = ".",
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    regex: bool = True,
    case_sensitive: bool = False,
    context: int = 2,
    max_results: int | None = 1000,
) -> GrepResult:
    """Search files with bounded output and a ten-second execution deadline.

    Returns partial results and a notice when a limit is reached. Searches at
    most 8 MiB per file, returns excerpts for long lines, and caps collected
    output at 1 MiB. Oversized model-facing responses may be saved temporarily
    by the runtime. A timed-out regex worker is killed and reaped.

    Args:
        pattern: Regex or literal pattern to search for (up to 4096 characters).
        path: File or directory to search. Defaults to the current directory.
        include_globs: Optional include patterns, such as src/**/*.py.
        exclude_globs: Optional excludes; .git, node_modules, __pycache__, and lock files are always excluded.
        regex: Interpret the pattern as a regex; set false for literal text.
        case_sensitive: Require matching letter case when true.
        context: Lines before and after each match, from 0 to 100.
        max_results: Requested match limit, from 1 to 10000. None uses the hard limit of 10000.
    """
    if len(pattern) > 4096 or not 0 <= context <= 100 or (max_results is not None and not 1 <= max_results <= 10_000):
        return GrepResult(
            success=False, matches=[],
            error="Use a pattern of at most 4096 characters, context from 0 to 100, and max_results from 1 to 10000 (or null).",
        )
    arguments = dict(
        pattern=pattern, path=str(Path(path).absolute()), include_globs=include_globs,
        exclude_globs=exclude_globs, regex=regex, case_sensitive=case_sensitive,
        context=context, max_results=max_results,
    )
    timed_out = False
    try:
        worker = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tools.virtual_computer._search_worker",
            cwd=Path(__file__).resolve().parents[2],
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        communication = asyncio.create_task(worker.communicate(json.dumps(arguments).encode()))
        try:
            try:
                output, _ = await asyncio.wait_for(asyncio.shield(communication), _SEARCH_TIMEOUT_SECONDS)
            except TimeoutError:
                timed_out = True
                if worker.returncode is None:
                    worker.kill()
                output, _ = await communication
        finally:
            # Cancellation of the tool must not leave its regex worker alive.
            if worker.returncode is None:
                worker.kill()
            await communication
            await worker.wait()
        matches = []
        for line in output.splitlines():
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue  # A timeout can interrupt the last protocol line.
            if "match" in record:
                matches.append(GrepMatch.model_validate(record["match"]))
            elif "result" in record:
                return GrepResult.model_validate({**record["result"], "matches": matches})
        return GrepResult(
            success=bool(matches), matches=matches, truncated=True,
            searched_files=len({match.file_path for match in matches}),
            notice=(f"Search stopped after {_SEARCH_TIMEOUT_SECONDS:g} seconds; results are incomplete. "
                    "Narrow the path or simplify the regex (regex=false searches literal text)."
                    if timed_out else "Search worker exited before completion; results are incomplete."),
            error=None if matches else ("Search timed out." if timed_out else "Search worker failed."),
        )
    except OSError:
        logger.exception("Could not start grep worker")
        return GrepResult(success=False, matches=[], error="Could not start search. Retry with a narrower request.")
