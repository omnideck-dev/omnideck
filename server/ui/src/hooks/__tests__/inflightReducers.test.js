import { describe, expect, it } from 'vitest';
import { reduceInflightContent } from '../../features/conversation/events/reduceInflight.js';

const AGENT = 'root.test.1';

describe('reduceInflightContent', () => {
    it('returns prev unchanged when both content and thinking are empty', () => {
        const prev = { agentId: AGENT, content: 'a', thinking: '' };
        expect(reduceInflightContent(prev, AGENT, 0, '', '')).toBe(prev);
    });

    it('creates a fresh inflight when prev is null', () => {
        expect(reduceInflightContent(null, AGENT, 0, 'hello', '')).toEqual({
            agentId: AGENT, content: 'hello', thinking: '',
        });
    });

    it('accumulates content and thinking while streaming the same iteration', () => {
        const prev = { agentId: AGENT, content: 'hel', thinking: 'reas' };
        expect(reduceInflightContent(prev, AGENT, 0, 'lo', 'oning')).toEqual({
            agentId: AGENT, content: 'hello', thinking: 'reasoning',
        });
    });

    it('replaces the inflight when content arrives for a different agent', () => {
        const prev = { agentId: 'other', content: 'a', thinking: '' };
        expect(reduceInflightContent(prev, AGENT, 0, 'fresh', '')).toEqual({
            agentId: AGENT, content: 'fresh', thinking: '',
        });
    });

    it('drops sub-agent content (depth>0) so it does not flash in the main chat', () => {
        // Sub-agent deltas drive the per-agent activity log via
        // APPEND_STREAM_CHUNK, not the chat's inflight bubble.
        const prev = { agentId: AGENT, content: 'root work', thinking: '' };
        expect(reduceInflightContent(prev, 'root.test.1.research.1', 1, 'sub work', 'sub thinking')).toBe(prev);
    });

    it('drops sub-agent content even when prev is null', () => {
        expect(reduceInflightContent(null, 'sub.1', 1, 'sub work', '')).toBe(null);
    });
});
