import { describe, expect, it } from 'vitest';
import { _mergeCompactions } from '../useStreamingChat.js';

const _user = (content) => ({ role: 'user', content });
const _assistant = (id) => ({ id, role: 'assistant', entries: [] });
const _start = (i) => ({
    id: `evt_start_${i}`, type: 'agent_started',
    agent_id: `root.test.${i}`, parent_agent_id: null,
});
const _iter = (id) => ({ id, type: 'iteration' });
const _compaction = (id, keptFromId, summary = 'summary') => ({
    id, type: 'compaction',
    kept_from_id: keptFromId,
    summary_text: summary,
    user_intent_summary: null,
    timestamp: '2026-01-01T00:00:30',
    stats: { scope: { user_messages: 1, iterations: 1, tool_results: 0 } },
    audit: { model: 'm', elapsed_seconds: 1.0 },
});

describe('_mergeCompactions', () => {
    it('returns ui messages unchanged when there are no events', () => {
        const uiMessages = [_user('hi'), _assistant('a0')];
        expect(_mergeCompactions(uiMessages, [])).toBe(uiMessages);
    });

    it('returns ui messages unchanged when no compaction events', () => {
        const events = [_start(1)];
        const uiMessages = [_user('hi'), _assistant('a0')];
        expect(_mergeCompactions(uiMessages, events)).toBe(uiMessages);
    });

    it('places chip before the assistant whose iteration is kept_from_id', () => {
        // Compaction fired during turn 2 with kept_from_id pointing to
        // an iteration of turn 2 → chip lands BEFORE turn 2's assistant
        // message (between turn 2's user message and turn 2's assistant).
        const events = [
            _start(1), _iter('iter1_t1'),
            _start(2), _iter('iter1_t2'), _compaction('c1', 'iter1_t2'),
        ];
        const uiMessages = [
            _user('u1'), _assistant('a0'),
            _user('u2'), _assistant('a1'),
        ];
        const out = _mergeCompactions(uiMessages, events);
        expect(out.map((m) => m.role)).toEqual([
            'user', 'assistant',                // turn 1
            'user', 'compaction', 'assistant',  // turn 2 user + chip + turn 2 assistant
        ]);
    });

    it('places multiple compactions before the turn each kept_from_id belongs to', () => {
        const events = [
            _start(1), _iter('iter_t1'), _compaction('c1', 'iter_t1', 's1'),
            _start(2), _iter('iter_t2'), _compaction('c2', 'iter_t2', 's2'),
            _start(3), _iter('iter_t3'),
        ];
        const uiMessages = [
            _user('u1'), _assistant('a0'),
            _user('u2'), _assistant('a1'),
            _user('u3'), _assistant('a2'),
        ];
        const out = _mergeCompactions(uiMessages, events);
        expect(out.map((m) => m.role)).toEqual([
            'user', 'compaction', 'assistant',
            'user', 'compaction', 'assistant',
            'user', 'assistant',
        ]);
        expect(out[1].summaryText).toBe('s1');
        expect(out[4].summaryText).toBe('s2');
    });

    it('ignores sub-agent agent_started events when assigning turn idx', () => {
        const sub_start = {
            id: 'evt_sub', type: 'agent_started',
            agent_id: 'root.test.1.sub.1', parent_agent_id: 'root.test.1',
        };
        const events = [
            _start(1), sub_start, _iter('iter1_t1'),
            _start(2), _iter('iter1_t2'), _compaction('c1', 'iter1_t2'),
        ];
        const uiMessages = [
            _user('u1'), _assistant('a0'),
            _user('u2'), _assistant('a1'),
        ];
        const out = _mergeCompactions(uiMessages, events);
        // Chip lands before turn 2's assistant, not turn 1's.
        expect(out.map((m) => m.role)).toEqual([
            'user', 'assistant',
            'user', 'compaction', 'assistant',
        ]);
    });

    it('falls back to compaction event position when kept_from_id is unknown', () => {
        // Migrator-synthesized compactions whose kept_from_id points
        // outside the loaded events: fall back to "the turn the
        // compaction event itself sits in".
        const events = [
            _start(1),
            _compaction('c1', 'evt_missing'),
            _start(2),
        ];
        const uiMessages = [
            _user('u1'), _assistant('a0'),
            _user('u2'), _assistant('a1'),
        ];
        const out = _mergeCompactions(uiMessages, events);
        // Compaction event sits at turn-idx 0 (between turn 1 start and
        // turn 2 start) → chip lands before turn 1's assistant.
        expect(out.map((m) => m.role)).toEqual([
            'user', 'compaction', 'assistant',
            'user', 'assistant',
        ]);
    });

    it('appends trailing compactions whose turn has no rendered assistant', () => {
        const events = [
            _start(1), _iter('iter_t1'),
            _start(2), _iter('iter_t2'), _compaction('c1', 'iter_t2'),
        ];
        // Only one assistant message rendered — c1 targets turn 2 which
        // didn't materialize. Trail it at the end.
        const uiMessages = [_user('u1'), _assistant('a0')];
        const out = _mergeCompactions(uiMessages, events);
        expect(out.map((m) => m.role)).toEqual([
            'user', 'assistant', 'compaction',
        ]);
    });

    it('emits a compaction msg with all fields needed by the chip', () => {
        const compaction = {
            ..._compaction('c1', 'iter_t1', 'summary text'),
            user_intent_summary: 'user is shopping',
        };
        const events = [_start(1), _iter('iter_t1'), compaction];
        const out = _mergeCompactions([_user('u'), _assistant('a0')], events);
        const chip = out.find((m) => m.role === 'compaction');
        expect(chip).toBeDefined();
        expect(chip.summaryText).toBe('summary text');
        expect(chip.userIntentSummary).toBe('user is shopping');
        expect(chip.stats).toBeDefined();
        expect(chip.stats.scope.user_messages).toBe(1);
    });
});
