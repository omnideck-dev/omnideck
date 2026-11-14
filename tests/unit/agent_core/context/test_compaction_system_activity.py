"""Compaction keeps app notes, such as goal wakeups, out of the user's intent history."""

from unittest.mock import AsyncMock, patch

from agent_core.context import GOAL_STATE_PREFIX, GOAL_WAKEUP_PREFIX, SYSTEM_ACTIVITY_PREFIX, ConversationHistory
from agent_core.context._models import ContextStats
from agent_core.events import CompactionPayload
from agent_runtime._compaction import LLMCompactionStrategy

_SETTINGS = {"compaction_provider": "test-provider", "compaction_model": "test-model", "compaction_options": {}}


async def compact(messages: list[dict]) -> tuple[CompactionPayload, AsyncMock]:
    history = ConversationHistory([{"role": "system", "content": "You are helpful."}, *messages])
    strategy = LLMCompactionStrategy(threshold=0.5, keep_recent_groups=1, summary_model="test-model")
    payloads: list = []
    with patch.object(strategy, "_summarize", new_callable=AsyncMock) as summarize, \
         patch.object(strategy, "_extract_intent", new_callable=AsyncMock) as extract, \
         patch("agent_runtime._compaction.publish_event", side_effect=lambda event: payloads.append(event.payload)), \
         patch("agent_runtime._compaction.load_settings", return_value=_SETTINGS):
        summarize.return_value = ("Summary.", "test-model")
        extract.return_value = "The user wants the reunion planned."
        await strategy.apply(history, ContextStats(context_used=800, context_limit=1000))
    compactions = [payload for payload in payloads if isinstance(payload, CompactionPayload)]
    assert len(compactions) == 1
    return compactions[0], extract


async def test_wakeup_is_not_saved_as_user_intent():
    payload, extract = await compact([
        {"role": "user", "content": "Plan the family reunion"},
        {"role": "assistant", "content": "Started a plan."},
        {"role": "user", "content": f"{GOAL_WAKEUP_PREFIX}\nA goal run started.\nPlan step: Book the pavilion"},
        {"role": "assistant", "content": "Called the parks office."},
        {"role": "assistant", "content": "Waiting on a reply."},
    ])
    extract.assert_not_awaited()
    assert payload.user_intent_summary is None


async def test_every_system_activity_note_is_skipped_for_intent():
    _payload, extract = await compact([
        {"role": "user", "content": "Plan the family reunion"},
        {"role": "assistant", "content": "Started a plan."},
        {"role": "user", "content": f"{GOAL_WAKEUP_PREFIX}\nA goal run started.\nPlan step: Book the pavilion"},
        {"role": "assistant", "content": "Called the parks office."},
        {"role": "user", "content": f"{GOAL_STATE_PREFIX}\nThe goal changed since you last read it."},
        {"role": "assistant", "content": "Read the goal again."},
        {"role": "user", "content": f"{SYSTEM_ACTIVITY_PREFIX} something new]\nAn app note."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Also invite the cousins"},
        {"role": "assistant", "content": "Added the cousins."},
        {"role": "assistant", "content": "Done for now."},
    ])
    extract.assert_awaited_once()
    assert extract.await_args.args[0] == ["Plan the family reunion", "Also invite the cousins"]
