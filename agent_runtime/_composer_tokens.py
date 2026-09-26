"""Composer message enrichment for `/skill` and `@agent /skill` chat tokens.

The chat composer lets a user type `/skill-name` (load a skill into the
current agent's own run) or `@agent-name /skill-name` (spawn a subagent with
that profile to do the work) — normally by picking one from the composer's
own autocomplete overlay. Neither the browser nor this module drives the
underlying tools directly — instead a token that resolves to a real,
currently-available skill/profile is rewritten into an explicit
natural-language instruction naming its id and the intended tool, and the
root agent's own tool-calling loop (`spawn_agent`, `load_skill`) does the
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

from agents._agent_profiles import AgentProfile
from agents._agent_profiles import list_agent_profiles as _list_store_profiles
from skills._store import SkillRecord, list_skill_records

# Matches a trigger only at the start of the message or after whitespace, so
# "user@host/path" or "a/b" mid-word never counts as a token.
_TOKEN_RE = re.compile(
    r"(?:(?<=^)|(?<=\s))"
    r"(?:@(?P<agent>\S+)\s+)?"
    r"/(?P<skill>\S+)",
)


def _resolve_skill(ref: str, skills: list[SkillRecord]) -> SkillRecord | None:
    lowered = ref.lower()
    for skill in skills:
        if skill.name.lower() == lowered or skill.id.lower() == lowered:
            return skill
    return None


def _resolve_profile(ref: str, profiles: list[AgentProfile]) -> AgentProfile | None:
    lowered = ref.lower()
    for profile in profiles:
        if profile.name.lower() == lowered or profile.id.lower() == lowered:
            return profile
    return None


def _render_delegate(profile: AgentProfile, skill: SkillRecord, args: str) -> str:
    agent_desc = f'agent profile "{profile.name}" (id: {profile.id})'
    skill_desc = f'skill "{skill.name}" (id: {skill.id})'
    task = f'load {skill_desc} and use it to: {args}' if args else f'load {skill_desc} and use it'
    return (
        f'Spawn a subagent using {agent_desc} to perform this task: {task}. '
        f'Use the spawn_agent tool with profile="{profile.id}".'
    )


def _render_load(skill: SkillRecord, args: str) -> str:
    skill_desc = f'skill "{skill.name}" (id: {skill.id})'
    action = f'then use it to: {args}' if args else 'then use it'
    return (
        f'Load {skill_desc} into your own current session using the load_skill tool, '
        f'{action}. Do not spawn a subagent for this — handle it yourself in this '
        f'conversation.'
    )


def enrich_composer_message(text: str) -> str:
    """Rewrite resolvable `/skill` and `@agent /skill` tokens into tool instructions.

    Scans left-to-right for `@agent-name /skill-name` (delegate to a
    subagent) and standalone `/skill-name` (load into the current run) at
    word boundaries. Only a token whose name(s) resolve against the current
    skill/profile stores is replaced, in place, by a natural-language
    instruction naming the resolved id and the tool to call; everything
    else — unresolved tokens, and all text between/around tokens — passes
    through byte-for-byte. A message with no matches at all, or where
    nothing resolves, is returned unchanged.
    """
    matches = list(_TOKEN_RE.finditer(text))
    if not matches:
        return text

    skills = list_skill_records()
    enabled_profiles = _list_store_profiles(include_disabled=False)

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
        agent_ref = match.group("agent")
        skill_ref = match.group("skill")

        if agent_ref is not None:
            profile = _resolve_profile(agent_ref, enabled_profiles)
            skill = _resolve_skill(skill_ref, skills)
            if profile is not None and skill is not None:
                pieces.append(_render_delegate(profile, skill, args) + trailing_ws)
                resolved_count += 1
            else:
                pieces.append(span_text)
        else:
            skill = _resolve_skill(skill_ref, skills)
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
