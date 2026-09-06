# Plan: Server-Side Draft Store for Routine Building Tools

## Problem
The current `begin_routine → add_task → commit_routine` flow requires the LLM to
pass a complex `draft` dict back and forth between tool calls. This fails because:

1. `_execute_tool_call` stringifies dict results with `str()` (Python repr, single quotes)
2. `_coerce_value` has no `dict` handler to parse strings back into dicts
3. The LLM sees Python repr and can't reliably reproduce valid JSON from it

## Solution: Server-Side Draft Store
Replace the `draft: dict` parameter with a `draft_id: str` token. Drafts live
in a module-level dict, never serialized to the LLM.

### Changes

#### 1. `tasks/_tools.py` — Core implementation
- Add `_drafts: dict[str, dict[str, Any]]` module-level store
- `begin_routine()` → returns `draft_id` string instead of dict
- `add_task(draft_id, ...)` → looks up draft by ID, returns same `draft_id`
- `commit_routine(draft_id)` → looks up draft, commits, cleans up
- Add `_draft_store.py` or keep inline (inline is simpler for ephemeral state)

#### 2. `sdk/skills/default_skills/routine_planner.json` — Update prompt
- Change "pass it into the next call" → "pass the draft_id into the next call"
- Document the new token-based flow

#### 3. `tests/unit/tasks/test_tools.py` — Update tests
- `create_routine` helper: use `begin_routine` → `add_task` → `commit_routine` flow
- All tests should work with the new token-based API

#### 4. `sdk/tools/_helpers.py` — Defensive fix (secondary)
- Add `dict` coercion in `_coerce_value` so strings get JSON-parsed back to dicts
- Use `json.dumps()` instead of `str()` for non-string results
- These are general fixes that help any tool returning dicts

## Testing
- Run `just tests-unit` to verify all unit tests pass
- Run `just tests-e2e routines` for e2e routine tests