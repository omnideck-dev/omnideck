"""Text the app writes for the model, shown in the model's view and kept apart in compaction."""

from pathlib import Path

import pytest

from agent_core.context import APP_TEXT_PREFIX, pinned_message
from agent_core.context._view import _SUMMARY_PREFIX, build_llm_view
from agent_runtime._compaction import _user_contents
from tests.unit.agent_core.context._event_builders import ROOT, _compaction, _iter, _started, _user

pytestmark = [pytest.mark.unit]


def note(text: str, evt_id: str = "evt_n", event_type: str = "goal") -> dict:
    return {**_user(ROOT, "", evt_id=evt_id), "type": event_type, "model_text": text}


@pytest.mark.parametrize("event_type", ["goal", "error", "file_output"])
def test_any_event_with_model_text_shows_as_a_notice(event_type):
    messages = build_llm_view([_started(ROOT, "Agent"), _user(ROOT, "Hi"), note("Read the plan.", event_type=event_type)])
    assert messages[-1] == {"role": "user", "content": f"{APP_TEXT_PREFIX}\nRead the plan."}


def test_event_without_model_text_is_not_shown():
    events = [_started(ROOT, "Agent"), _user(ROOT, "Hi"), {**note("", "evt_x")}]
    assert build_llm_view(events) == [{"role": "user", "content": "Hi"}]


def test_a_notice_can_open_the_view():
    assert build_llm_view([_started(ROOT, "Agent"), note("A run started.")]) == [
        {"role": "user", "content": f"{APP_TEXT_PREFIX}\nA run started."},
    ]


def test_notice_first_chat_opens_with_the_summary_after_compaction():
    events = [
        _started(ROOT, "Agent"), note("A run started. Old step.", "n1"),
        _iter(ROOT, 0, content="Worked.", evt_id="i1"), _user(ROOT, "Next?", evt_id="u2"),
        _iter(ROOT, 1, content="Kept.", evt_id="i2"),
        _compaction(ROOT, "Earlier work.", kept_from_id="u2", kept_to_id="i2"),
    ]
    messages = build_llm_view(events)
    assert messages[0] == {"role": "user", "content": _SUMMARY_PREFIX + "Earlier work."}
    assert "Old step" not in str(messages)
    assert pinned_message(events) is None


def test_typed_first_message_stays_pinned_after_compaction():
    events = [
        _started(ROOT, "Agent"), _user(ROOT, "Plan the reunion", evt_id="u1"),
        _iter(ROOT, 0, content="Worked.", evt_id="i1"), _user(ROOT, "Next?", evt_id="u2"),
        _compaction(ROOT, "Earlier work.", kept_from_id="u2", kept_to_id="u2"),
    ]
    messages = build_llm_view(events)
    assert messages[:2] == [
        {"role": "user", "content": "Plan the reunion"},
        {"role": "assistant", "content": _SUMMARY_PREFIX + "Earlier work."},
    ]


def test_user_message_model_text_replaces_content_with_no_prefix_then_attachments():
    attachment = {"filename": "a.txt", "content_type": "text/plain", "path": "/home/computron/uploads/a.txt"}
    event = {**_user(ROOT, "Saturday", attachments=[attachment]), "model_text": "The answer is Saturday."}
    assert build_llm_view([_started(ROOT, "Agent"), event])[0]["content"] == (
        "The answer is Saturday.\n\n[Attached files written to virtual computer]\n"
        "  - a.txt (text/plain) -> /home/computron/uploads/a.txt"
    )


def test_user_message_with_model_text_can_be_pinned_after_compaction():
    first = {**_user(ROOT, "Saturday", evt_id="u1"), "model_text": "The answer is Saturday."}
    events = [
        _started(ROOT, "Agent"), first, _iter(ROOT, 0, content="Worked.", evt_id="i1"),
        _user(ROOT, "Next?", evt_id="u2"),
        _compaction(ROOT, "Earlier work.", kept_from_id="u2", kept_to_id="u2"),
    ]
    assert build_llm_view(events)[0] == {"role": "user", "content": "The answer is Saturday."}


def test_intent_merge_collects_user_messages_only():
    events = [
        _started(ROOT, "Agent"), _user(ROOT, "Plan the reunion", evt_id="u1"),
        note("A run started.", "n1"), _user(ROOT, "Use the park", evt_id="u2"),
    ]
    assert _user_contents(events) == ["Plan the reunion", "Use the park"]


def test_model_view_and_compaction_name_no_feature():
    root = Path(__file__).resolve().parents[4]
    sources = [*sorted((root / "agent_core" / "context").glob("*.py")), root / "agent_runtime" / "_compaction.py"]
    for path in sources:
        text = path.read_text().lower()
        assert "goal" not in text.replace('"goal",', ""), path
