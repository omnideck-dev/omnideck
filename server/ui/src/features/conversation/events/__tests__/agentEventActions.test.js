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

    it('builds ordered stream and tool-call actions', () => {
        expect(getAgentEventActions(event('content', {
            content: 'answer', thinking: 'reasoning',
        })).ordered).toEqual([{
            type: 'APPEND_STREAM_CHUNK',
            agentId: 'agent-1',
            content: 'answer',
            thinking: 'reasoning',
        }]);

        expect(getAgentEventActions(event('iteration', {
            content: 'complete answer',
            thinking: 'complete reasoning',
            tool_calls: [
                { name: 'shell', arguments: { cmd: 'ls' } },
                { name: 'browser', arguments: null },
            ],
        })).ordered).toEqual([{
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

    it('builds ordered activity records', () => {
        expect(getAgentEventActions(event('spawn_requested', {
            correlation_id: 'spawn-1',
        })).ordered[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: { type: 'spawn_requested', correlationId: 'spawn-1', timestamp: TIME },
        });

        expect(getAgentEventActions(event('file_output', {
            filename: 'report.md', content_type: 'text/markdown', path: '/tmp/report.md',
        })).ordered[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: {
                type: 'file_output', filename: 'report.md', path: '/tmp/report.md', timestamp: TIME,
            },
        });

        expect(getAgentEventActions(event('compaction', {
            summary_text: 'summary', user_intent_summary: 'intent', stats: { removed: 3 },
        })).ordered[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: {
                type: 'compaction', summaryText: 'summary', userIntentSummary: 'intent', timestamp: TIME,
            },
        });
    });

    it('adds errors only to sub-agent activity', () => {
        expect(getAgentEventActions(event('error', { message: 'root failed' })).ordered).toEqual([]);
        expect(getAgentEventActions(event('error', {
            depth: 1, message: 'child failed',
        })).ordered[0]).toMatchObject({
            type: 'APPEND_ACTIVITY',
            entry: { type: 'error', message: 'child failed', timestamp: TIME },
        });
    });

    it('ignores unrelated and agentless events', () => {
        expect(getAgentEventActions(event('audio_playback'))).toEqual({ immediate: [], ordered: [] });
        expect(getAgentEventActions(event('content', { agent_id: null, content: 'ignored' })))
            .toEqual({ immediate: [], ordered: [] });
        expect(getAgentEventActions(null)).toEqual({ immediate: [], ordered: [] });
    });
});
