"""Keep oversized tool output out of context while preserving it temporarily."""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_MAX_INLINE_BYTES = 64 * 1024
_DEFAULT_INLINE_BYTES = 16 * 1024


class ToolResultCapHook:
    """Spill large results to temporary files before publishing them to history.

    Use UTF-8 bytes rather than assuming four characters per token. A result
    receives only a fraction of the context, with an absolute ceiling; this is
    a conservative output allowance, not an exact provider token calculation.
    """

    def __init__(self, context_window: int) -> None:
        self._max_bytes = (
            max(512, min(_MAX_INLINE_BYTES, context_window // 4))
            if context_window > 0 else _DEFAULT_INLINE_BYTES
        )

    def after_tool(
        self, tool_name: str, tool_arguments: object, tool_result: str,
    ) -> str:
        """Return a preview and temporary path when output exceeds its allowance."""
        if not isinstance(tool_result, str):
            return tool_result
        data = tool_result.encode("utf-8", errors="replace")
        if len(data) <= self._max_bytes:
            return tool_result
        path = None
        try:
            # Random exclusive file creation, mode 0600; tool names/arguments
            # never become path components. Respect TMPDIR for isolated tests.
            with tempfile.NamedTemporaryFile(prefix="omnideck-tool-result-", suffix=".txt", delete=False) as output:
                path = output.name
                output.write(data)
        except OSError:
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            logger.warning("Could not save oversized output from %s", tool_name, exc_info=True)
            return (
                "Tool output exceeded the inline limit and could not be saved to a temporary file. "
                "Retry with a narrower request or write the result to a file explicitly."
            )
        preview = data[:min(512, self._max_bytes // 4)].decode("utf-8", errors="ignore")
        return (
            f"Tool output exceeded the inline limit ({self._max_bytes} bytes). "
            f"Full output ({len(data)} bytes) saved to temporary file: {path}\n"
            "Inspect selected sections with existing file/search tools; avoid reading the whole file back. "
            "For a very long line, use shell byte ranges. Save anything needed permanently elsewhere. "
            "If the temporary file is gone, rerun the original tool.\n"
            f"Preview (incomplete):\n{preview}"
        )
