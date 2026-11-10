"""Composer message enrichment for `/skill` chat tokens.

The chat composer lets a user type `/skill-name` to load a skill into the
current agent's own run — normally by picking one from the composer's own
autocomplete overlay. Neither the browser nor this module drives the
underlying tool directly — instead a token that resolves to a real skill is
rewritten into an explicit natural-language instruction naming its id and
the `load_skill` tool, and the root agent's own tool-calling loop does the
actual work.

A token that *doesn't* resolve — a typo, a stale name, or just incidental
text that happens to look like one (a file path such as `/etc/hosts`, a URL
segment) — is left completely untouched: no rewrite, no hint. The overlay is
the only sanctioned way to produce a real token; anything else reaching here
unresolved was never actually a command, so there's nothing to explain.

This rewrite runs as a model-facing-only view transform applied when the LLM
message list is derived, never on the message before it's stored or
broadcast — the persisted event and the transcript the user sees always keep
their exact typed text.
"""

import re

from skills._store import SkillRecord, list_skill_records

# Matches a trigger only at the start of the message or after whitespace, so
# "user@host/path" or "a/b" mid-word never counts as a token.
_TOKEN_RE = re.compile(r"(?:(?<=^)|(?<=\s))/(?P<skill>\S+)")


def _slugify(text: str) -> str:
    """Kebab-case a display name for token matching.

    Must stay behaviorally identical to the frontend's copy of this
    algorithm (``server/ui/src/utils/slugify.js``) — there's no shared
    runtime between the two, so any drift here silently breaks resolution
    for names the composer already slugified client-side.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _resolve_skill(ref: str, skills: list[SkillRecord]) -> SkillRecord | None:
    lowered = ref.lower()
    for skill in skills:
        if skill.name.lower() == lowered or skill.id.lower() == lowered:
            return skill
    slug_matches = [skill for skill in skills if _slugify(skill.name) == lowered]
    return slug_matches[0] if len(slug_matches) == 1 else None


# A user who types the bare token with nothing after it hasn't given a task —
# they want the skill's own output (a joke, a draft, whatever it does),
# delivered directly. Without this, "load X and use it" reads like a system
# test spec (it even names a raw skill id), and models asked to "use" a
# freshly loaded capability with no further direction default to reporting on
# whether the mechanism worked instead of just doing the thing.
_NO_ARGS_DIRECTIVE = "use it — respond with what it produces, not a report on whether it loaded"


def _render_load(skill: SkillRecord, args: str) -> str:
    skill_desc = f'skill "{skill.name}" (id: {skill.id})'
    action = f'then use it to: {args}' if args else f'then {_NO_ARGS_DIRECTIVE}'
    return (
        f'Load {skill_desc} into your own current session using the load_skill tool, '
        f'{action}. Do not spawn a subagent for this — handle it yourself in this '
        f'conversation.'
    )


def enrich_composer_message(text: str) -> str:
    """Rewrite resolvable `/skill` tokens into `load_skill` instructions.

    Scans left-to-right for `/skill-name` at word boundaries. Only a token
    whose name resolves against the current skill store is replaced, in place, by a natural-language
    instruction naming the resolved id and the tool to call; everything
    else — unresolved tokens, and all text between/around tokens — passes
    through byte-for-byte. A message with no matches at all, or where
    nothing resolves, is returned unchanged.
    """
    matches = list(_TOKEN_RE.finditer(text))
    if not matches:
        return text

    skills = list_skill_records()

    resolved_count = 0
    pieces = [text[:matches[0].start()]]
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        span_text = text[match.start():end]
        raw_args = text[match.end():end]
        args = raw_args.strip()
        # Preserved so a rendered instruction butts up against whatever
        # follows it (the next token, or end of message) with the same
        # whitespace the user's own text had there, instead of running two
        # sentences together with no separator.
        trailing_ws = raw_args[len(raw_args.rstrip()):]
        skill = _resolve_skill(match.group("skill"), skills)
        if skill is not None:
            pieces.append(_render_load(skill, args) + trailing_ws)
            resolved_count += 1
        else:
            pieces.append(span_text)

    if resolved_count == 0:
        return text

    body = "".join(pieces)
    if resolved_count == 1:
        return body

    return (
        "Perform the following in order, waiting for each step's result "
        f"before starting the next:\n{body}"
    )
