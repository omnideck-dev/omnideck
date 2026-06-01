import { describe, expect, it, vi } from 'vitest';
import { replayEventsToAgentState } from '../_replayEvents.js';

const _agentStarted = (agentId, opts = {}) => ({
    type: 'agent_started',
    agent_id: agentId,
    agent_name: opts.name || agentId.toUpperCase(),
    parent_agent_id: opts.parent || null,
    correlation_id: opts.correlation || null,
    instruction: opts.instruction || '',
    timestamp: '2026-01-01T00:00:00',
});
const _agentCompleted = (agentId, status = 'success') => ({
    type: 'agent_completed', agent_id: agentId, status,
});
const _iter = (agentId, opts = {}) => ({
    type: 'iteration', agent_id: agentId,
    iteration_index: opts.idx ?? 0,
    thinking: opts.thinking ?? null,
    content: opts.content ?? null,
    tool_calls: opts.toolCalls || [],
    timestamp: '2026-01-01T00:00:01',
});

describe('replayEventsToAgentState', () => {
    it('is a no-op for empty / missing inputs', () => {
        const d = vi.fn();
        replayEventsToAgentState(null, d);
        replayEventsToAgentState(undefined, d);
        replayEventsToAgentState([], d);
        expect(d).not.toHaveBeenCalled();
    });

    it('dispatches AGENT_STARTED with the real agent_id and parent link', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            _agentStarted('root.test.1.sub.1', { parent: 'root.test.1' }),
        ], d);
        const startedCalls = d.mock.calls.filter(([a]) => a.type === 'AGENT_STARTED');
        expect(startedCalls).toHaveLength(2);
        expect(startedCalls[0][0].agentId).toBe('root.test.1');
        expect(startedCalls[0][0].parentAgentId).toBe(null);
        expect(startedCalls[1][0].agentId).toBe('root.test.1.sub.1');
        expect(startedCalls[1][0].parentAgentId).toBe('root.test.1');
    });

    it('dispatches AGENT_COMPLETED with the persisted status and event timestamp', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            {
                type: 'agent_completed', agent_id: 'root.test.1',
                status: 'error', timestamp: '2026-01-01T00:01:00+00:00',
            },
        ], d);
        const completed = d.mock.calls.find(([a]) => a.type === 'AGENT_COMPLETED');
        expect(completed[0]).toMatchObject({
            type: 'AGENT_COMPLETED', agentId: 'root.test.1', status: 'error',
        });
        expect(completed[0].timestamp).toBe(Date.parse('2026-01-01T00:01:00+00:00'));
    });

    it('passes UTC-suffixed timestamps straight through to AGENT_STARTED', () => {
        // Backend writes ISO with +00:00; migration 007 normalises any
        // legacy naive timestamps to the same shape, so the FE no longer
        // does its own UTC normalisation.
        const d = vi.fn();
        replayEventsToAgentState([{
            ..._agentStarted('root.test.1'),
            timestamp: '2026-06-01T16:28:03.477604+00:00',
        }], d);
        const started = d.mock.calls[0][0];
        expect(started.timestamp).toBe(Date.parse('2026-06-01T16:28:03.477604+00:00'));
    });

    it('expands an iteration into a stream chunk + one APPEND_ACTIVITY per tool_call', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            _iter('root.test.1', {
                idx: 0, thinking: 'reasoning', content: 'response',
                toolCalls: [
                    { id: 'tc1', name: 'shell', arguments: { cmd: 'ls' } },
                    { id: 'tc2', name: 'write_file', arguments: { path: '/a' } },
                ],
            }),
        ], d);
        const types = d.mock.calls.map(([a]) => a.type);
        expect(types).toEqual([
            'AGENT_STARTED', 'APPEND_STREAM_CHUNK', 'APPEND_ACTIVITY', 'APPEND_ACTIVITY',
        ]);
        const stream = d.mock.calls[1][0];
        expect(stream).toMatchObject({
            type: 'APPEND_STREAM_CHUNK',
            agentId: 'root.test.1',
            content: 'response',
            thinking: 'reasoning',
        });
        const activities = d.mock.calls.filter(([a]) => a.type === 'APPEND_ACTIVITY');
        expect(activities[0][0].entry.name).toBe('shell');
        expect(activities[1][0].entry.name).toBe('write_file');
    });

    it('emits no stream chunk when the iteration has neither thinking nor content', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            _iter('root.test.1', { toolCalls: [{ id: 't', name: 'shell' }] }),
        ], d);
        const types = d.mock.calls.map(([a]) => a.type);
        expect(types).toEqual(['AGENT_STARTED', 'APPEND_ACTIVITY']);
    });

    it('dispatches spawn_requested as an activity entry on the agent that requested it', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            {
                type: 'spawn_requested', agent_id: 'root.test.1',
                correlation_id: 'c-1', timestamp: '2026-01-01T00:00:02',
            },
        ], d);
        const sr = d.mock.calls.find(([a]) => a.type === 'APPEND_ACTIVITY' && a.entry.type === 'spawn_requested');
        expect(sr[0]).toMatchObject({
            agentId: 'root.test.1',
            entry: { type: 'spawn_requested', correlationId: 'c-1' },
        });
    });

    it('dispatches terminal_output as UPDATE_TERMINAL on the emitting agent', () => {
        const d = vi.fn();
        const ev = {
            type: 'terminal_output', agent_id: 'root.test.1',
            cmd_id: 'cmd-1', stdout: 'hello\n', status: 'streaming',
        };
        replayEventsToAgentState([
            _agentStarted('root.test.1'), ev,
        ], d);
        const t = d.mock.calls.find(([a]) => a.type === 'UPDATE_TERMINAL');
        expect(t[0]).toEqual({
            type: 'UPDATE_TERMINAL', agentId: 'root.test.1', event: ev,
        });
    });

    it('dispatches browser_screenshot as UPDATE_BROWSER_SNAPSHOT', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            {
                type: 'browser_screenshot', agent_id: 'root.test.1',
                url: 'https://example.com', title: 'Example',
                screenshot: 'iVBORw0K...', tab_id: 'tab-1',
            },
        ], d);
        const snap = d.mock.calls.find(([a]) => a.type === 'UPDATE_BROWSER_SNAPSHOT');
        expect(snap[0]).toMatchObject({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root.test.1',
            snapshot: {
                url: 'https://example.com', title: 'Example',
                screenshot: 'iVBORw0K...', tabId: 'tab-1',
            },
        });
    });

    it('dispatches file_output as an activity entry', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.test.1'),
            {
                type: 'file_output', agent_id: 'root.test.1',
                filename: 'r.pdf', content_type: 'application/pdf',
                path: '/home/computron/r.pdf', timestamp: '2026-01-01T00:00:03',
            },
        ], d);
        const fo = d.mock.calls.find(([a]) => a.type === 'APPEND_ACTIVITY' && a.entry.type === 'file_output');
        expect(fo[0].entry).toMatchObject({
            type: 'file_output', filename: 'r.pdf',
            content_type: 'application/pdf', path: '/home/computron/r.pdf',
        });
    });

    it('skips events without an agent_id where one is required', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            { type: 'spawn_requested', correlation_id: 'c' },
            { type: 'file_output', filename: 'x' },
            { type: 'iteration', content: 'orphan' },
        ], d);
        expect(d).not.toHaveBeenCalled();
    });

    it('skips chat-only event types so they do not pollute useAgentState', () => {
        // user_message / tool_result / compaction / context_usage are
        // consumed by the chat or context meter, not the agent state.
        const d = vi.fn();
        replayEventsToAgentState([
            { type: 'user_message', agent_id: 'root', content: 'hi', attachments: [] },
            { type: 'tool_result', agent_id: 'root', tool_call_id: 'tc', content: 'ok' },
            { type: 'compaction', agent_id: 'root', summary_text: 's' },
            { type: 'context_usage', agent_id: 'root', context_used: 100 },
        ], d);
        expect(d).not.toHaveBeenCalled();
    });

    it('replays a full root + sub-agent conversation in order', () => {
        const d = vi.fn();
        replayEventsToAgentState([
            _agentStarted('root.1'),
            _iter('root.1', { content: 'delegating', toolCalls: [{ id: 't', name: 'spawn_agent' }] }),
            { type: 'spawn_requested', agent_id: 'root.1', correlation_id: 'c-1' },
            _agentStarted('root.1.sub.1', { parent: 'root.1', correlation: 'c-1' }),
            _iter('root.1.sub.1', { content: '42' }),
            _agentCompleted('root.1.sub.1'),
            _iter('root.1', { idx: 1, content: 'answer is 42' }),
            _agentCompleted('root.1'),
        ], d);
        const types = d.mock.calls.map(([a]) => a.type);
        expect(types).toEqual([
            'AGENT_STARTED',
            'APPEND_STREAM_CHUNK',     // root iter 0 content
            'APPEND_ACTIVITY',          // root iter 0 tool_call (spawn_agent)
            'APPEND_ACTIVITY',          // spawn_requested
            'AGENT_STARTED',            // sub-agent
            'APPEND_STREAM_CHUNK',     // sub-agent iter content
            'AGENT_COMPLETED',          // sub-agent done
            'APPEND_STREAM_CHUNK',     // root iter 1 content
            'AGENT_COMPLETED',          // root done
        ]);
    });
});
