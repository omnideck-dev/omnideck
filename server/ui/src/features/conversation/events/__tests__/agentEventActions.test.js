import { describe, expect, it } from 'vitest';
import { getAgentEventActions } from '../agentEventActions.js';

const TIMESTAMP = '2026-07-20T12:00:00.000Z';
const TIME = Date.parse(TIMESTAMP);

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        timestamp: TIMESTAMP,
        agent_id: 'agent-1',
        depth: 0,
        ...fields,
    };
}

describe('getAgentEventActions', () => {
    it('builds immediate lifecycle and context actions', () => {
        expect(getAgentEventActions(event('agent_started', {
            agent_name: 'Researcher',
            parent_agent_id: 'root-1',
            instruction: 'Investigate',
            correlation_id: 'spawn-1',
        })).immediate).toEqual([{
            type: 'AGENT_STARTED',
            agentId: 'agent-1',
            agentName: 'Researcher',
            parentAgentId: 'root-1',
            instruction: 'Investigate',
            correlationId: 'spawn-1',
            timestamp: TIME,
        }]);

        expect(getAgentEventActions(event('agent_completed', {
            status: 'success',
        })).immediate).toEqual([{
            type: 'AGENT_COMPLETED',
            agentId: 'agent-1',
            status: 'success',
            timestamp: TIME,
        }]);

        expect(getAgentEventActions(event('context_usage', {
            iteration: 2,
            max_iterations: 8,
            context_used: 1200,
            context_limit: 4000,
            fill_ratio: 0.3,
            compaction_threshold: 0.8,
        })).immediate).toEqual([{
            type: 'UPDATE_ITERATION',
            agentId: 'agent-1',
            iteration: 2,
            maxIterations: 8,
            contextUsage: {
                context_used: 1200,
                context_limit: 4000,
                fill_ratio: 0.3,
                compaction_threshold: 0.8,
            },
        }]);
    });

    it('builds batched stream and tool-call actions', () => {
        expect(getAgentEventActions(event('content', {
            depth: 1, content: 'answer', thinking: 'reasoning',
        })).batched).toEqual([{
            type: 'APPEND_STREAM_CHUNK',
            agentId: 'agent-1',
            content: 'answer',
            thinking: 'reasoning',
        }]);

        expect(getAgentEventActions(event('iteration', {
            depth: 1,
            content: 'complete answer',
            thinking: 'complete reasoning',
            tool_calls: [
                { name: 'shell', arguments: { cmd: 'ls' } },
                { name: 'browser', arguments: null },
            ],
        })).batched).toEqual([{
            type: 'FINALIZE_AGENT_ITERATION',
            agentId: 'agent-1',
            content: 'complete answer',
            thinking: 'complete reasoning',
            toolCalls: [
                { name: 'shell', arguments: { cmd: 'ls' } },
                { name: 'browser', arguments: null },
            ],
            timestamp: TIME,
        }]);
    });

    it('builds batched activity records', () => {
        expect(getAgentEventActions(event('spawn_requested', {
            depth: 1, correlation_id: 'spawn-1',
        })).batched[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: { type: 'spawn_requested', correlationId: 'spawn-1', timestamp: TIME },
        });

        expect(getAgentEventActions(event('file_output', {
            depth: 1, filename: 'report.md', content_type: 'text/markdown', path: '/tmp/report.md',
        })).batched[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: {
                type: 'file_output', filename: 'report.md', path: '/tmp/report.md', timestamp: TIME,
            },
        });

        expect(getAgentEventActions(event('compaction', {
            depth: 1,
            summary_text: 'summary',
            user_intent_summary: 'intent',
            stats: { removed: 3 },
        })).batched[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: {
                type: 'compaction', summaryText: 'summary', userIntentSummary: 'intent', timestamp: TIME,
            },
        });
    });

    it('does not duplicate root transcript output in agent activity', () => {
        expect(getAgentEventActions(event('content', {
            content: 'answer', thinking: 'reasoning',
        })).batched).toEqual([]);
        expect(getAgentEventActions(event('iteration', {
            content: 'complete answer',
            thinking: null,
            tool_calls: [],
        })).batched).toEqual([]);
        expect(getAgentEventActions(event('file_output', {
            filename: 'report.md',
            content_type: 'text/markdown',
            path: '/tmp/report.md',
        })).batched).toEqual([]);
    });

    it('adds errors only to sub-agent activity', () => {
        expect(getAgentEventActions(event('error', { message: 'root failed' })).batched).toEqual([]);
        expect(getAgentEventActions(event('error', {
            depth: 1, message: 'child failed',
        })).batched[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: { type: 'error', message: 'child failed', timestamp: TIME },
        });
    });

    it('ignores unrelated and agentless events', () => {
        expect(getAgentEventActions(event('audio_playback'))).toEqual({ immediate: [], batched: [] });
        expect(getAgentEventActions(event('content', { agent_id: null, content: 'ignored' })))
            .toEqual({ immediate: [], batched: [] });
        expect(getAgentEventActions(null)).toEqual({ immediate: [], batched: [] });
    });
});
