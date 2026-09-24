"""Application-configured LLM compaction and model resource management."""

import asyncio
import logging
from datetime import datetime

from rich.console import Console

from agent_core.providers import ProviderError
from providers import get_provider
from rich.panel import Panel
from rich.text import Text

from agent_core.events import (
    AgentEvent,
    CompactionPayload,
    CompactionScope,
    CompactionStats,
    publish_event,
)
from settings import load_settings

from agent_core.context import ContextStats, ConversationHistory, TriggerPoint

logger = logging.getLogger(__name__)
_console = Console(stderr=True)

# Default cap on tool result chars in serialized summarization input.
# Overridden per tool type below — code tools need more content since
# the assistant messages are often empty and all signal is in the result.
_TOOL_RESULT_CAP = 200

# Per-tool-type result caps.
# Code tools: the file/grep/bash output IS the data — assistant messages
#   are typically empty (content=0) so the tool result is the only signal.
# Browser tools: page snapshots are large but mostly navigation noise;
#   the assistant already synthesizes findings in its content. A moderate
#   cap captures structured data (prices, ratings) without including menus.
# Default (unknown tools): conservative 200 chars.
_TOOL_RESULT_CAPS: dict[str, int] = {
    # Code — higher cap than default. Agent messages typically already synthesize
    # file contents, so the tool result is supplementary context. 1500 chars
    # captures the module docstring, imports, and first class definition.
    "read_file": 1500,
    "grep": 1500,
    "run_bash_cmd": 1500,
    "list_dir": 800,
    "apply_text_patch": 400,
    "replace_in_file": 400,
    "write_file": 300,
    # Browser — moderate cap, assistant synthesizes page content
    "open_url": 500,
    "read_page": 800,
    "browse_page": 500,
    "scroll_page": 400,
    "click": 200,
    "fill_field": 200,
}

# Maximum chars of the ``thinking`` field to include when the assistant
# message has no visible content.  In coding conversations the assistant
# often makes tool calls with empty content — all analysis lives in
# ``thinking``.  Including an excerpt gives the summarizer context about
# *why* a tool was called (e.g. "reading file to find pause button").
_THINKING_CAP = 200


# Approximate characters per token for estimating chunk boundaries.
_CHARS_PER_TOKEN = 4


def _parse_iso_seconds(ts: str) -> float | None:
    """Parse an ISO-8601 timestamp to a POSIX float, or return None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return None

# Fraction of the summarizer's context window to use for input.
# Leaves room for the system prompt (~500 tokens) and generated output
# (num_predict, typically 2048 tokens).
_CTX_INPUT_FRACTION = 0.6

# Maximum time (seconds) for a single summarizer LLM call. If the model
# takes longer (e.g. runaway generation, contention), the call is cancelled
# and compaction is skipped rather than blocking the agent indefinitely.
_CALL_TIMEOUT = 180


_SUMMARIZE_PROMPT = (
    "You are a summarizer. Condense the following conversation into a factual "
    "reference document that the assistant can use to continue working. The "
    "conversation may be browser research, code analysis, or both.\n"
    "\n"
    "{objective_line}"
    "You MUST use EXACTLY this structure with these exact headings. Do not use "
    "any other format. Do not write prose or commentary. Start your response "
    "with '## Completed Work'.\n"
    "\n"
    "## Completed Work\n"
    "List every fact, finding, and result produced so far as bullet points.\n"
    "Focus on RESULTS and FINDINGS, not the steps taken to get them.\n"
    "For code tasks: document what key files CONTAIN (APIs, class definitions, "
    "critical logic, function signatures), not just that files were read.\n"
    "For research tasks: document what was found at each source.\n"
    "\n"
    "## Key Data\n"
    "List all specific reference data needed to continue the work:\n"
    "- Research: URLs/links, prices, ratings, dates, addresses, phone numbers, "
    "version numbers\n"
    "- Code: file paths, function/method signatures, class definitions, API "
    "contracts, import paths, error messages, test results, shell command output\n"
    "Format as a structured list grouped by type. If no key data was gathered, "
    "write \"None\".\n"
    "\n"
    "## Current State\n"
    "Describe what is happening RIGHT NOW at the end of the conversation.\n"
    "What was the assistant doing? What does it still need to do to complete "
    "the objective? Include any in-progress work, unresolved errors, or "
    "pending actions. If not applicable, write \"None\".\n"
    "\n"
    "RULES:\n"
    "- Your output MUST start with '## Completed Work' and contain all three "
    "sections above. No other format is acceptable.\n"
    "- Preserve FACTS and DATA, not process. Drop operational details "
    "(navigation steps, scroll positions, viewport positions, failed commands, "
    "file line numbers) unless they indicate an active blocker.\n"
    "  Browser WRONG: 'Navigated to Google Flights, applied nonstop filter, "
    "clicked search'\n"
    "  Browser RIGHT: 'Searched Google Flights nonstop AUS→ORD Apr 10-12. "
    "Best: American $634, United $714, Delta $558'\n"
    "  Code WRONG: 'Read agent_core/context/_history.py'\n"
    "  Code RIGHT: 'ConversationHistory (agent_core/context/_history.py): owns the "
    "in-memory event log, subscribe(handler)/unsubscribe()/add_event(event) "
    "for observer fan-out, drain_observers() waits for async observers'\n"
    "- For code: preserve key signatures, field names, and behavioural details "
    "found in file contents — these are the primary value of code analysis.\n"
    "- For research: MUST INCLUDE URLs needed to revisit results. Omit "
    "intermediate navigation URLs (search engines, category listings).\n"
    "- MUST INCLUDE all prices, ratings, quantities, dates, and numerical data.\n"
    "- If the input contains a prior summary, RE-CONDENSE it together with the "
    "new information into a single tight summary. Integrate and deduplicate — "
    "do NOT copy the prior summary verbatim. The output should be shorter or "
    "the same length unless significant new facts were added.\n"
    "- Never drop specific details (numbers, names, URLs, paths, signatures) in "
    "favor of vague descriptions like 'highly-rated' or 'well-known'.\n"
    "- Be concise but exhaustive in facts.\n"
    "- Do NOT echo these instructions — replace them with actual content."
)


def _build_summarize_prompt(objective: str = "") -> str:
    """Build the summarizer system prompt, optionally injecting the objective."""
    if objective:
        objective_line = (
            f'THE AGENT\'S OBJECTIVE: "{objective}"\n'
            "Prioritize information the agent needs to complete this objective.\n\n"
        )
    else:
        objective_line = ""
    return _SUMMARIZE_PROMPT.format(objective_line=objective_line)


_SUMMARY_PREFIX = "[Conversation summary — earlier messages were compacted]\n\n"

# Prefix for the synthetic user message that replaces the stale pinned
# first user message after intent extraction (experiment 29).
_INTENT_PREFIX = "[User intent history]\n"

# Prompt for extracting the user's current intent from multiple user
# messages.  Only called when the compactable range contains more than
# one user message, indicating the user changed topics or refined their
# request during the conversation.
_INTENT_EXTRACTION_PROMPT = (
    "You will be given a sequence of user messages from a multi-turn "
    "conversation with an AI assistant. The user may have changed topics "
    "or given new instructions over the course of the conversation.\n\n"
    "Write a concise history of the user's inputs that shows how their "
    "requests evolved. Start with the original request and trace through "
    "topic changes, refinements, and redirections to arrive at the current "
    "intent. Use a compact format — one line per phase. Mark the current "
    "active request clearly with [CURRENT] prefix.\n\n"
    "Output ONLY the history. Be concise — each line should be one "
    "sentence max."
)



def _compaction_error_message(model: str, detail: str) -> str:
    """Build the user-facing message for a compaction failure.

    Compaction runs after a model call. When it fails, the conversation keeps
    growing toward its limit, so the failure is raised rather than swallowed
    and reaches the user through the turn's normal error path.
    """
    return (
        f"This conversation is long enough that it needs to be summarized to "
        f"keep going, but that step failed: the compaction model '{model}' "
        f"{detail}. Open Settings and make sure the correct compaction model is "
        f"configured and its provider is available (a valid key with remaining "
        f"quota), then send your message again."
    )


class LLMCompactionStrategy:
    """Summarizes old conversation history when context fills up.

    When the context fill ratio exceeds *threshold*, sends the oldest
    messages to an LLM for summarization and replaces them with a compact
    summary. The most recent messages are preserved verbatim, with the
    boundary determined by assistant message groups to avoid splitting
    tool calls from their results.

    Args:
        threshold: Fill ratio above which the strategy activates (0.0–1.0).
        keep_recent_groups: Number of recent assistant message groups to
            preserve. Each group is an assistant message plus its tool
            results. Any user or other messages interleaved between kept
            groups are also preserved.
        summary_model: Model identifier string override.
            Falls back to the ``summary`` section in config.
    """

    def __init__(
        self,
        threshold: float = 0.75,
        keep_recent_groups: int = 2,
        summary_model: str | None = None,
    ) -> None:
        self._threshold = threshold
        self._keep_recent_groups = keep_recent_groups
        self._summary_model = summary_model

    @property
    def trigger(self) -> TriggerPoint:
        return TriggerPoint.BEFORE_MODEL_CALL

    def should_apply(self, history: ConversationHistory, stats: ContextStats) -> bool:
        return stats.fill_ratio >= self._threshold

    async def apply(self, history: ConversationHistory, stats: ContextStats) -> None:
        """Summarize old messages and publish a CompactionPayload event.

        The strategy never mutates ``history``. After this method returns,
        the next read of ``history.messages`` derives the compacted view
        from the new event in the log.
        """
        non_system = history.non_system_messages
        first_user_idx, has_first_user = _find_first_user(non_system)
        pin_offset = 1 if has_first_user else 0

        body = non_system[pin_offset:]
        keep_count = _count_kept_by_assistant_groups(
            body, self._keep_recent_groups,
        )
        if keep_count >= len(body):
            return

        compactable = body[:-keep_count] if keep_count > 0 else body
        if not compactable:
            return

        # Resolve kept_from_id / kept_to_id from the agent's own event log.
        # kept_from_id is the event id of the (keep_recent_groups)-th-from-
        # last iteration event — everything earlier (within this agent's
        # scope) gets compacted. kept_to_id is the most recent event for
        # this agent at the moment compaction fires.
        kept_from_id, kept_to_id = self._resolve_kept_bounds(history)
        if kept_from_id is None or kept_to_id is None:
            return

        all_user_contents = []
        for m in non_system:
            if m.get("role") == "user":
                content = m.get("content") or ""
                if content and not content.startswith(_SUMMARY_PREFIX):
                    all_user_contents.append(content)

        prior_summary = _extract_prior_summary(compactable)

        resolved = self._resolve_model()
        if resolved is None:
            return
        _resolved_provider, resolved_model, _resolved_options = resolved

        import time as _time
        t0 = _time.monotonic()
        try:
            summary, model_name = await self._summarize(
                compactable, prior_summary,
            )
        except TimeoutError as exc:
            logger.warning(
                "LLMCompactionStrategy: compaction timed out after %ds",
                _CALL_TIMEOUT,
            )
            await _unload_model(resolved_model)
            raise ProviderError(
                _compaction_error_message(resolved_model, f"timed out after {_CALL_TIMEOUT}s"),
                retryable=True,
            ) from exc
        except ProviderError as exc:
            logger.warning("LLMCompactionStrategy: summarizer call failed: %s", exc)
            await _unload_model(resolved_model)
            raise ProviderError(
                _compaction_error_message(resolved_model, f"failed: {exc}"),
                retryable=exc.retryable,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            logger.exception("LLMCompactionStrategy: compaction failed")
            await _unload_model(resolved_model)
            raise ProviderError(
                _compaction_error_message(resolved_model, "failed with an unexpected error"),
            ) from exc
        elapsed = _time.monotonic() - t0

        # If the agent received multiple distinct user messages, the first
        # one likely no longer reflects current intent. Ask the summarizer
        # to produce a consolidated intent history; the new compaction
        # event will replace the first user message's content with this at
        # build time.
        user_intent_summary = None
        if has_first_user and len(all_user_contents) > 1:
            try:
                user_intent_summary = await self._extract_intent(all_user_contents)
                logger.info(
                    "LLMCompactionStrategy: extracted intent from %d user messages",
                    len(all_user_contents),
                )
            except Exception:
                logger.exception(
                    "Intent extraction failed, keeping original first user message",
                )

        _log_compaction(stats, len(compactable), summary)

        input_char_count = sum(len(m.get("content") or "") for m in compactable)
        presentation_stats = self._compute_stats(
            history=history,
            kept_from_id=kept_from_id,
            context_before=stats.context_used,
            context_limit=stats.context_limit,
            input_char_count=input_char_count,
            summary_text=summary,
            model=model_name,
            elapsed_seconds=round(elapsed, 1),
        )
        try:
            publish_event(AgentEvent(payload=CompactionPayload(
                type="compaction",
                kept_from_id=kept_from_id,
                kept_to_id=kept_to_id,
                summary_text=summary,
                user_intent_summary=user_intent_summary,
                stats=presentation_stats,
            )))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to publish compaction event")

        await _unload_model(model_name)

    def _resolve_kept_bounds(
        self, history: ConversationHistory,
    ) -> tuple[str | None, str | None]:
        """Return (kept_from_id, kept_to_id) from this agent's event log.

        kept_from_id is the event id of the iteration that anchors the
        recent-kept group; kept_to_id is the most recent event for the
        agent. Returns ``(None, None)`` if there aren't enough iterations
        yet to compact safely.
        """
        # Scope to this thread via the same membership the derived view
        # uses (root view for the root, exact agent_id for a sub-agent).
        # Keying on agent_name instead would reset the iteration count on a
        # mid-conversation profile switch (the name carries the profile),
        # so a switch into a smaller window could never trigger compaction.
        my_events = history.scoped_events
        if not my_events:
            return None, None
        my_iterations = [e for e in my_events if e["type"] == "iteration"]
        if len(my_iterations) < self._keep_recent_groups:
            return None, None
        kept_from_id = my_iterations[-self._keep_recent_groups]["id"]
        kept_to_id = my_events[-1]["id"]
        return kept_from_id, kept_to_id

    def _compute_stats(
        self,
        *,
        history: ConversationHistory,
        kept_from_id: str,
        context_before: int,
        context_limit: int,
        input_char_count: int,
        summary_text: str,
        model: str,
        elapsed_seconds: float,
    ) -> CompactionStats:
        """Compute presentation stats for the chip panel at compaction time.

        Walks the agent's event log to count what's being compacted,
        derives an estimated post-compaction context size from the chars
        replaced vs. the summary's own size, and bundles everything into
        a CompactionStats. All approximations use chars/4 ≈ tokens.
        """
        # Same thread scope as _resolve_kept_bounds — kept_from_id was
        # resolved against this list, so the stats range must walk it too.
        my_events = history.scoped_events

        # The range this compaction summarized: from just after the
        # previous compaction (or log start) up to but not including
        # kept_from_id.
        prior_idx = None
        for i in range(len(my_events) - 1, -1, -1):
            if my_events[i].get("type") == "compaction":
                prior_idx = i
                break
        range_start = (prior_idx + 1) if prior_idx is not None else 0
        kept_idx = None
        for i, e in enumerate(my_events):
            if e.get("id") == kept_from_id:
                kept_idx = i
                break
        range_end = kept_idx if kept_idx is not None else len(my_events)
        compacted = my_events[range_start:range_end]

        scope = CompactionScope(
            user_messages=sum(1 for e in compacted if e.get("type") == "user_message"),
            iterations=sum(1 for e in compacted if e.get("type") == "iteration"),
            tool_results=sum(1 for e in compacted if e.get("type") == "tool_result"),
        )
        spanned_seconds = None
        if compacted:
            first_ts = _parse_iso_seconds(compacted[0].get("timestamp", ""))
            last_ts = _parse_iso_seconds(compacted[-1].get("timestamp", ""))
            if first_ts is not None and last_ts is not None:
                spanned_seconds = max(0.0, last_ts - first_ts)

        summary_chars = len(summary_text)
        summary_lines = summary_text.count("\n") + 1 if summary_text else 0
        summary_tokens = summary_chars // _CHARS_PER_TOKEN

        # Estimate post-compaction context: subtract the input chars the
        # summarizer replaced, add the summary's own size.
        input_tokens = input_char_count // _CHARS_PER_TOKEN
        context_after_est = max(0, context_before - input_tokens + summary_tokens)
        saved_tokens = max(0, context_before - context_after_est)
        saved_ratio = (saved_tokens / context_before) if context_before > 0 else 0.0

        return CompactionStats(
            context_before=context_before,
            context_after=context_after_est,
            context_limit=context_limit,
            saved_tokens=saved_tokens,
            saved_ratio=saved_ratio,
            spanned_seconds=spanned_seconds,
            scope=scope,
            summary_chars=summary_chars,
            summary_tokens=summary_tokens,
            summary_lines=summary_lines,
            model=model,
            input_char_count=input_char_count,
            elapsed_seconds=elapsed_seconds,
        )

    async def _summarize(
        self,
        messages: list[dict],
        prior_summary: str | None = None,
        objective: str = "",
    ) -> tuple[str, str]:
        """Summarize messages, chunking if necessary.

        For short conversations, serializes and summarizes in a single call.
        For long conversations, splits into chunks, summarizes each, then
        merges the chunk summaries. The chunk threshold scales with the
        summarizer's configured context window.
        """
        import copy

        _, _, options = self._resolve_model() or (None, None, {})
        num_ctx = options.get("num_ctx", 8192) if isinstance(options, dict) else 8192
        chunk_threshold = int(num_ctx * _CHARS_PER_TOKEN * _CTX_INPUT_FRACTION)
        chunk_target = chunk_threshold // 2

        # Serialize to check total size.
        serialized = _serialize_messages(copy.deepcopy(messages))
        if len(serialized) <= chunk_threshold:
            return await self._call_summarizer(
                serialized, prior_summary, objective,
            )

        # Split messages into chunks and summarize each independently.
        chunks = _split_into_chunks(messages, chunk_target)
        logger.info(
            "Chunked summarization: %d messages → %d chunks",
            len(messages), len(chunks),
        )

        chunk_summaries: list[str] = []
        model_name = ""
        for i, chunk in enumerate(chunks):
            chunk_text = _serialize_messages(copy.deepcopy(chunk))
            # Include prior summary context only in the first chunk.
            ps = prior_summary if i == 0 else None
            summary, model_name = await self._call_summarizer(
                chunk_text, ps, objective,
            )
            chunk_summaries.append(summary)

        # Merge chunk summaries in a final pass.
        merged_input = "\n\n---\n\n".join(
            f"[Summary of part {i + 1}/{len(chunk_summaries)}]\n{s}"
            for i, s in enumerate(chunk_summaries)
        )
        final_summary, model_name = await self._call_summarizer(
            merged_input, prior_summary=None, objective=objective,
        )
        return final_summary, model_name

    async def _call_summarizer(
        self,
        conversation_text: str,
        prior_summary: str | None = None,
        objective: str = "",
    ) -> tuple[str, str]:
        """Call the summarization LLM and return (summary_text, model_name)."""
        resolved = self._resolve_model()
        assert resolved is not None
        provider_name, model, options = resolved
        provider = get_provider(provider_name)

        user_content = ""
        if prior_summary:
            user_content += (
                "PRIOR SUMMARY (from a previous compaction — integrate into "
                "your output, re-condensing where possible):\n\n"
                + prior_summary
                + "\n\n---\n\nNEW MESSAGES since last compaction:\n\n"
            )
        user_content += conversation_text

        system_prompt = _build_summarize_prompt(objective)
        response = await asyncio.wait_for(
            provider.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                think=False,
                options=options,
            ),
            timeout=_CALL_TIMEOUT,
        )
        return response.message.content or "", model

    async def _extract_intent(self, user_messages: list[str]) -> str:
        """Extract the user's current intent from multiple user messages.

        Called during compaction when the conversation has more than one
        user message, indicating the user may have changed topics.  Uses
        the same model as the summarizer.
        """
        resolved = self._resolve_model()
        assert resolved is not None
        provider_name, model, options = resolved
        provider = get_provider(provider_name)

        # Build the user content with numbered messages.
        # Truncate individual messages to keep the input focused.
        user_content = ""
        for i, msg in enumerate(user_messages):
            text = msg[:500] + "..." if len(msg) > 500 else msg
            user_content += f"\n--- Message {i + 1} ---\n{text}\n"

        response = await asyncio.wait_for(
            provider.chat(
                model=model,
                messages=[
                    {"role": "system", "content": _INTENT_EXTRACTION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                think=False,
                options={
                    **(options if isinstance(options, dict) else {}),
                    "temperature": 0,
                },
            ),
            timeout=60,
        )
        return response.message.content or ""

    def _resolve_model(self) -> tuple[str, str, dict] | None:
        """Determine the (provider, model, options) to use for summarization.

        The model comes from an explicit constructor arg or the
        ``compaction_model`` setting; the provider from ``compaction_provider``;
        inference options from ``compaction_options``. Returns None if no
        model/provider is configured.
        """
        settings = load_settings()
        options = dict(settings.get("compaction_options") or {})
        provider = settings.get("compaction_provider") or ""
        model = self._summary_model or settings.get("compaction_model") or ""

        if model and provider:
            return provider, model, options

        logger.warning("No compaction model/provider configured — compaction disabled")
        return None


async def _unload_model(model: str) -> None:
    """Unload a model from Ollama to free VRAM."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama", "stop", model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=30)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.debug("Unload model %s timed out after 30s", model)
    except Exception:
        logger.debug("Failed to unload model %s", model)


def _log_compaction(
    stats: ContextStats,
    msg_count: int,
    summary: str,
) -> None:
    """Render a Rich panel showing the context summarization result."""
    header = Text()
    header.append(f"Compacted {msg_count} messages", style="bold")
    header.append(f"  fill={stats.fill_ratio:.0%}", style="yellow")
    header.append(f"  → {len(summary):,} chars", style="green")

    _console.print(Panel(
        Text(summary),
        title="[bold magenta]Context Summary[/bold magenta]",
        subtitle=header,
        border_style="magenta",
        expand=False,
    ))


def _count_kept_by_assistant_groups(
    messages: list[dict],
    keep_groups: int,
) -> int:
    """Count how many messages from the tail to keep based on assistant groups.

    Walks backward through *messages* counting assistant messages (with or
    without tool calls). When *keep_groups* assistant messages have been
    found, the boundary is set right before the earliest one found. Any
    non-assistant messages (user messages, tool results) that fall between
    or after the kept assistant messages are included automatically.

    Returns the number of raw messages to keep from the end.
    """
    if keep_groups <= 0 or not messages:
        return 0

    assistant_count = 0
    boundary = len(messages)

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant":
            assistant_count += 1
            boundary = i
            if assistant_count >= keep_groups:
                break

    if assistant_count == 0:
        return 0

    return len(messages) - boundary


# Keys from tool call arguments worth including in the serialized summary.
# Maps tool name → list of argument keys to extract. Keys are checked in
# order; the first present key is used. Values over 200 chars are truncated.
_TOOL_ARG_KEYS: dict[str, list[str]] = {
    "write_file": ["path"],
    "read_file": ["path"],
    "apply_text_patch": ["path"],
    "replace_in_file": ["path"],
    "run_bash_cmd": ["cmd", "command"],
    "open_url": ["url"],
    "click": ["ref"],
    "fill_field": ["ref"],
    "grep": ["pattern", "query"],
    "list_dir": ["path"],
    "generate_image": ["prompt"],
    "describe_image": ["path", "image_path"],
}


def _summarize_tool_args(tool_name: str, fn: object) -> str:
    """Extract a short summary of tool call arguments for serialization."""
    keys = _TOOL_ARG_KEYS.get(tool_name)
    if not keys:
        return ""

    raw_args = getattr(fn, "arguments", None)
    if not raw_args and isinstance(fn, dict):
        raw_args = fn.get("arguments", {})
    if isinstance(raw_args, str):
        try:
            import json as _json
            raw_args = _json.loads(raw_args)
        except (ValueError, TypeError):
            return ""
    if not isinstance(raw_args, dict):
        return ""

    parts = []
    for key in keys:
        val = raw_args.get(key)
        if val is not None:
            val_str = str(val)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            parts.append(val_str)

    return ", ".join(parts)


# Patterns that indicate a tool result carries no useful information.
_TRIVIAL_PATTERNS = [
    "{'success': True",
    '{"success": true',
    "{'stdout': None, 'stderr': None, 'exit_code': 0}",
    "{'stdout': '', 'stderr': None, 'exit_code': 0}",
    "{'stdout': '', 'stderr': '', 'exit_code': 0}",
    "{'stdout': None, 'stderr': '', 'exit_code': 0}",
]


def _is_trivial_tool_result(content: str) -> bool:
    """Check if a tool result is trivially empty and can be skipped."""
    stripped = content.strip()
    if not stripped:
        return True
    for pattern in _TRIVIAL_PATTERNS:
        if stripped.startswith(pattern) and len(stripped) < 200:
            return True
    return False


def _find_first_user(non_system: list[dict]) -> tuple[int, bool]:
    """Return the index of the first user message and whether one was found."""
    for i, msg in enumerate(non_system):
        if msg.get("role") == "user":
            content = msg.get("content") or ""
            # New summaries use "assistant" role and are skipped naturally.
            # The prefix check is legacy safety for old conversations where
            # summaries had "user" role.
            if not content.startswith(_SUMMARY_PREFIX):
                return i, True
    return 0, False


def _extract_prior_summary(messages: list[dict]) -> str | None:
    """Find and return the most recent prior summary from old messages."""
    for msg in messages:
        content = msg.get("content") or ""
        if content.startswith(_SUMMARY_PREFIX):
            return content[len(_SUMMARY_PREFIX):]
    return None


def _split_into_chunks(
    messages: list[dict],
    target_size: int = 10_000,
) -> list[list[dict]]:
    """Split messages into chunks of approximately *target_size* characters.

    Keeps assistant + tool-call pairs together so a tool call and its
    result are never separated across chunks. A chunk may therefore
    exceed *target_size* when a long run of tool calls/results would
    otherwise straddle a boundary.
    """
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    current_size = 0

    for msg in messages:
        content = msg.get("content") or ""
        msg_size = len(content)

        # If adding this message would exceed the target and the chunk
        # already has content, start a new chunk — but never split a
        # tool-call / tool-result pair across chunks.
        if current_size + msg_size > target_size and current_chunk:
            # If the current message is a tool result and the last
            # message in the chunk is an assistant with tool_calls,
            # keep them together by deferring the split.
            if not _would_split_tool_pair(current_chunk, msg):
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0

        current_chunk.append(msg)
        current_size += msg_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _would_split_tool_pair(
    chunk: list[dict],
    next_msg: dict,
) -> bool:
    """Return True if appending *next_msg* to *chunk* would separate a
    tool-call / tool-result pair across chunks.

    Fires when *next_msg* is a tool result and the last message in
    *chunk* is either an assistant with ``tool_calls`` or another tool
    result — flushing here would put the call and its result(s) in
    different chunks.
    """
    if not chunk:
        return False

    last = chunk[-1]
    return next_msg.get("role") == "tool" and (
        # Next message is a tool result and the last message in the chunk
        # is the assistant that issued the tool call.
        (last.get("role") == "assistant" and bool(last.get("tool_calls")))
        # Or the last message is also a tool result — keep consecutive
        # tool results together with their originating assistant.
        or last.get("role") == "tool"
    )


def _serialize_messages(messages: list[dict]) -> str:
    """Serialize a list of messages into readable text for summarization.

    Browser tool results that return page snapshots are deduplicated — only
    the last snapshot per URL is kept in full, earlier ones are replaced with
    a short note. Individual tool results over ``_TOOL_RESULT_CAP`` are
    truncated.
    """
    _dedup_page_snapshots(messages)

    entries: list[str] = []

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content") or ""

        # Summary messages are handled separately via _extract_prior_summary().
        # Skip regardless of role to avoid double-inclusion (new summaries use
        # "assistant" role, legacy ones may still have "user").
        if content.startswith(_SUMMARY_PREFIX):
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            # Include a truncated thinking excerpt — it often contains
            # synthesized findings and reasoning that the visible content
            # lacks (e.g. "found the Agent class has 8 fields...").
            thinking = ""
            raw_thinking = msg.get("thinking") or ""
            if raw_thinking:
                thinking = raw_thinking[:_THINKING_CAP]
                if len(raw_thinking) > _THINKING_CAP:
                    thinking += "..."

            if tool_calls:
                tool_parts = []
                for tc in tool_calls:
                    fn = getattr(tc, "function", None) or tc.get("function", {})
                    name = getattr(fn, "name", None) or fn.get("name", "unknown")
                    args_summary = _summarize_tool_args(name, fn)
                    if args_summary:
                        tool_parts.append(f"{name}({args_summary})")
                    else:
                        tool_parts.append(name)
                tools_str = ", ".join(tool_parts)
                if content and thinking:
                    entries.append(
                        f"Assistant: {content}\n  (thinking: {thinking})\n  [Called: {tools_str}]",
                    )
                elif content:
                    entries.append(f"Assistant: {content}\n  [Called: {tools_str}]")
                elif thinking:
                    entries.append(
                        f"Assistant (thinking: {thinking})\n  [Called: {tools_str}]",
                    )
                else:
                    entries.append(f"Assistant: [Called: {tools_str}]")
            elif content and thinking:
                entries.append(f"Assistant: {content}\n  (thinking: {thinking})")
            elif content:
                entries.append(f"Assistant: {content}")
            elif thinking:
                entries.append(f"Assistant (thinking: {thinking})")

        elif role == "tool":
            tool_name = msg.get("tool_name", "unknown")
            if _is_trivial_tool_result(content):
                continue
            cap = _TOOL_RESULT_CAPS.get(tool_name, _TOOL_RESULT_CAP)
            if len(content) > cap:
                content = content[:cap] + "..."
            entries.append(f"Tool ({tool_name}): {content}")

        elif role == "user":
            entries.append(f"User: {content}")

    return "\n\n".join(entries)


def _dedup_page_snapshots(messages: list[dict]) -> None:
    """Replace earlier page snapshots for the same URL with a short note.

    Mutates *messages* in place. Only the last tool result containing a
    given base URL is kept in full; earlier duplicates are collapsed to
    ``[page snapshot — superseded by later snapshot]``.
    """
    import re

    # Build a map of base_url → index of last message with that URL.
    _PAGE_PREFIX_RE = re.compile(r"^\[Page: .+? \| (https?://[^\s|]+)")
    last_seen: dict[str, int] = {}
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        m = _PAGE_PREFIX_RE.match(content)
        if m:
            # Strip query params for dedup — same page, different scroll/state.
            base_url = m.group(1).split("?")[0]
            last_seen[base_url] = i

    # Replace earlier duplicates.
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content") or ""
        m = _PAGE_PREFIX_RE.match(content)
        if m:
            base_url = m.group(1).split("?")[0]
            if last_seen.get(base_url) != i:
                msg["content"] = "[page snapshot — superseded by later snapshot]"
