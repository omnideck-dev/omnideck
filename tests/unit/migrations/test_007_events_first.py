"""Migration tests for ``_007_events_first.synthesize_compaction_events``.

Focused on the bug we found in real data: migrated compaction events
were missing the ``stats`` block that drives the UI chip, so chips
showed sparse/incorrect counts on old conversations.
"""

from __future__ import annotations

import pytest

from datetime import datetime, timezone

from migrations._007_events_first import (
    Event,
    _depth_from_agent_id,
    _fmt_iso,
    _norm_ts,
    _parent_id_from_agent_id,
    _parse_iso,
    _scope_for_compacted_range,
    synthesize_compaction_events,
)


@pytest.mark.unit
def test_parse_iso_attaches_utc_tzinfo_to_naive_strings():
    """Legacy ``datetime.utcnow()`` ISO strings are naive but actually
    UTC — _parse_iso must attach tzinfo so downstream comparisons and
    formatted output land on a real timezone."""
    dt = _parse_iso("2026-06-01T16:28:03.477604")
    assert dt.tzinfo == timezone.utc


@pytest.mark.unit
def test_parse_iso_preserves_explicit_negative_offset():
    """A ``-05:00`` suffix is a valid tz marker, not a dash inside the
    date. The recovery branch used to strip it and silently UTC-tag
    the result, shifting the timestamp by hours."""
    dt = _parse_iso("2026-06-01T16:28:03-05:00")
    # 16:28 EST is 21:28 UTC.
    assert dt.utcoffset().total_seconds() == -5 * 3600
    assert dt.isoformat() == "2026-06-01T16:28:03-05:00"


@pytest.mark.unit
def test_fmt_iso_always_emits_timezone_suffix():
    # Naive input → coerced to UTC, suffix shows up in the output.
    naive = datetime(2026, 6, 1, 16, 28, 3, 477604)
    assert _fmt_iso(naive).endswith("+00:00")
    # tz-aware input passes through unchanged.
    aware = naive.replace(tzinfo=timezone.utc)
    assert _fmt_iso(aware) == "2026-06-01T16:28:03.477604+00:00"

@pytest.mark.unit
def test_depth_from_agent_id():
    # root.<name>.<n> is depth 0; each extra name/counter pair is a level.
    assert _depth_from_agent_id("root.computron.1") == 0
    assert _depth_from_agent_id("root.small_context_window.8") == 0
    assert _depth_from_agent_id("root.computron.1.researcher.2") == 1
    assert _depth_from_agent_id("root.a.1.b.2.c.3") == 2
    assert _depth_from_agent_id("root") == 0


@pytest.mark.unit
def test_parent_id_from_agent_id():
    # A depth-0 root has no parent; deeper ids drop their last pair.
    assert _parent_id_from_agent_id("root.computron.1") is None
    assert _parent_id_from_agent_id("root") is None
    assert _parent_id_from_agent_id("root.a.1.b.2") == "root.a.1"
    assert _parent_id_from_agent_id("root.a.1.b.2.c.3") == "root.a.1.b.2"


@pytest.mark.unit
def test_to_dict_sets_depth_on_every_event():
    # Without depth, the UI's depth>0 sub-agent filter can't hide
    # sub-agent traffic from the main chat (the migrated-conversation leak).
    root = Event(id="e1", type="user_message", timestamp="2026-01-01T00:00:00",
                 conversation_id="c1", agent_id="root.x.1", payload={})
    sub = Event(id="e2", type="user_message", timestamp="2026-01-01T00:00:00",
                conversation_id="c1", agent_id="root.x.1.sub.2", payload={})
    assert root.to_dict()["depth"] == 0
    assert sub.to_dict()["depth"] == 1


@pytest.mark.unit
def test_to_dict_derives_parent_for_agent_started_and_overrides_stale_depth():
    started = Event(
        id="e1", type="agent_started", timestamp="2026-01-01T00:00:00",
        conversation_id="c1", agent_id="root.x.1.sub.2",
        # stale depth carried in from a spread source payload must lose.
        payload={"agent_name": "SUB", "depth": 99},
    )
    d = started.to_dict()
    assert d["depth"] == 1
    assert d["parent_agent_id"] == "root.x.1"


@pytest.mark.unit
def test_norm_ts_normalizes_naive_and_missing():
    assert _norm_ts("2026-06-01T16:28:03.477604").endswith("+00:00")
    # Already tz-aware passes through.
    assert _norm_ts("2026-06-01T16:28:03+00:00").endswith("+00:00")
    # Missing/empty anchors to a parseable epoch, not an empty string.
    assert _parse_iso(_norm_ts("")).year == 1970
    assert _parse_iso(_norm_ts(None)).year == 1970


CONV = "c1"
ROOT_AGENT = "root.computron.1"


def _evt(type_: str, evt_id: str, *, agent_id: str = ROOT_AGENT,
         ts: str = "2026-01-01T00:00:00", **payload) -> Event:
    return Event(
        id=evt_id, type=type_, timestamp=ts,
        conversation_id=CONV, agent_id=agent_id, payload=payload,
    )


@pytest.mark.unit
def test_scope_for_compacted_range_counts_event_types():
    compacted = [
        _evt("user_message", "u1", content="hi"),
        _evt("iteration", "i1"),
        _evt("tool_result", "t1"),
        _evt("iteration", "i2"),
        _evt("user_message", "u2", content="more"),
        _evt("agent_completed", "ac1"),  # not in the LLM view, not counted
    ]
    scope = _scope_for_compacted_range(compacted)
    assert scope == {
        "user_messages": 2,
        "iterations": 2,
        "tool_results": 1,
    }


@pytest.mark.unit
def test_synthesized_compaction_embeds_stats_with_scope():
    """The migrator must emit ``stats.scope`` so the resumed chip shows
    real counts. This is the regression that left chips reading "1 turn"
    on conversations that had many turns compacted."""
    # Three pre-compaction turns, then the recent-kept iteration the
    # compaction collapses around.
    all_events = [
        _evt("agent_started", "as1"),
        _evt("user_message", "u1", content="t1"),
        _evt("iteration", "i1"),
        _evt("user_message", "u2", content="t2"),
        _evt("iteration", "i2"),
        _evt("tool_result", "t2_res"),
        _evt("user_message", "u3", content="t3"),
        _evt("iteration", "i3_last_owned"),
        _evt("iteration", "i4_kept_from"),  # first event after the compaction
        _evt("iteration", "i5"),
    ]

    # Match the migrator's expected shape: each summary record claims
    # its owned event ids via the lookup map.
    record = {
        "id": "rec1",
        "summary_text": "summary",
        "created_at": "2026-01-01T00:00:10",
        "model": "test-model",
        "input_char_count": 100,
        "elapsed_seconds": 0.5,
    }
    event_id_to_record_id = {
        "u1": "rec1", "i1": "rec1",
        "u2": "rec1", "i2": "rec1", "t2_res": "rec1",
        "u3": "rec1", "i3_last_owned": "rec1",
    }

    out = synthesize_compaction_events(
        records=[record],
        conversation_id=CONV,
        agent_id=ROOT_AGENT,
        event_id_to_record_id=event_id_to_record_id,
        all_events_in_order=all_events,
    )

    assert len(out) == 1
    comp = out[0]
    assert comp.type == "compaction"
    assert comp.payload["kept_from_id"] == "i4_kept_from"
    stats = comp.payload.get("stats")
    assert stats is not None, "migrator must embed stats on compaction"
    assert stats["scope"] == {
        "user_messages": 3,
        "iterations": 3,
        "tool_results": 1,
    }
    assert stats["summary_chars"] == len("summary")
    assert stats["summary_tokens"] == len("summary") // 4
    assert stats["summary_lines"] == 1


@pytest.mark.unit
def test_second_compaction_scope_excludes_events_consumed_by_the_first():
    """Sequential compactions must not double-count: a later compaction's
    scope only contains events the earlier one didn't already summarize."""
    all_events = [
        _evt("agent_started", "as1"),
        _evt("user_message", "u1", content="early"),
        _evt("iteration", "i1_owned_by_rec1"),
        _evt("iteration", "i2_kept_from_rec1"),
        _evt("user_message", "u2", content="later"),
        _evt("iteration", "i3_owned_by_rec2"),
        _evt("iteration", "i4_kept_from_rec2"),
    ]
    rec1 = {
        "id": "rec1", "summary_text": "s1",
        "created_at": "2026-01-01T00:00:10",
    }
    rec2 = {
        "id": "rec2", "summary_text": "s2",
        "created_at": "2026-01-01T00:00:20",
    }
    event_id_to_record_id = {
        "u1": "rec1", "i1_owned_by_rec1": "rec1",
        "u2": "rec2", "i3_owned_by_rec2": "rec2",
    }

    out = synthesize_compaction_events(
        records=[rec1, rec2],
        conversation_id=CONV,
        agent_id=ROOT_AGENT,
        event_id_to_record_id=event_id_to_record_id,
        all_events_in_order=all_events,
    )

    assert len(out) == 2
    scope1 = out[0].payload["stats"]["scope"]
    scope2 = out[1].payload["stats"]["scope"]
    assert scope1["user_messages"] == 1  # u1 only
    assert scope2["user_messages"] == 1  # u2 only — u1 already consumed
