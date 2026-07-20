import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import useStreamingChat from '../useStreamingChat.js';

const encoder = new TextEncoder();

function bodyFromBytes(bytes, splitPoints) {
    const chunks = [];
    let start = 0;
    for (const end of splitPoints) {
        chunks.push(bytes.slice(start, end));
        start = end;
    }
    chunks.push(bytes.slice(start));

    let index = 0;
    return {
        getReader: () => ({
            read: async () => {
                if (index >= chunks.length) return { done: true, value: undefined };
                return { done: false, value: chunks[index++] };
            },
        }),
    };
}

describe('useStreamingChat stream delivery', () => {
    afterEach(() => vi.restoreAllMocks());

    it('builds the expected turn when JSONL records cross byte chunks', async () => {
        const agentId = 'root.test.1';
        const records = [
            {
                id: 'start-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'agent_started', agent_id: agentId,
                    agent_name: 'TEST', parent_agent_id: null,
                },
            },
            {
                id: 'user-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'user_message', content: 'hello',
                    attachments: [], is_nudge: false,
                },
            },
            {
                id: 'iteration-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'iteration', iteration_index: 0,
                    content: 'world', thinking: null, tool_calls: [],
                },
            },
            {
                id: 'end-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'turn_end' },
            },
        ];
        const bytes = encoder.encode(`${records.map(JSON.stringify).join('\n')}\n`);
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromBytes(bytes, [7, 31, 83, 147]),
        });
        const onAgentAction = vi.fn();
        const { result } = renderHook(() => useStreamingChat({ onAgentAction }));

        await act(async () => {
            await result.current.sendMessage('hello', null, 'profile-1');
        });

        expect(result.current.isStreaming).toBe(false);
        expect(result.current.turns).toHaveLength(1);
        expect(result.current.turns[0]).toMatchObject({
            agentId,
            children: [
                { kind: 'user_prompt', content: 'hello' },
                { kind: 'iteration', content: 'world' },
            ],
        });
        expect(onAgentAction).toHaveBeenCalledWith(expect.objectContaining({
            type: 'AGENT_STARTED', agentId,
        }));
    });

    it('continues with later events when one live callback fails', async () => {
        const agentId = 'root.test.1';
        const records = [
            {
                id: 'snapshot-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'browser_screenshot', url: 'https://example.test',
                    title: 'Example', screenshot: 'base64-image',
                },
            },
            {
                id: 'start-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'agent_started', agent_id: agentId,
                    agent_name: 'TEST', parent_agent_id: null,
                },
            },
            {
                id: 'user-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'user_message', content: 'hello',
                    attachments: [], is_nudge: false,
                },
            },
            {
                id: 'iteration-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'iteration', iteration_index: 0,
                    content: 'still delivered', thinking: null, tool_calls: [],
                },
            },
            {
                id: 'end-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'turn_end' },
            },
        ];
        const bytes = encoder.encode(`${records.map(JSON.stringify).join('\n')}\n`);
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromBytes(bytes, [19, 71, 133]),
        });
        const onWorkspaceAction = vi.fn(() => {
            throw new Error('preview unavailable');
        });
        const { result } = renderHook(() => useStreamingChat({
            onWorkspaceAction,
            onAgentAction: vi.fn(),
        }));

        await act(async () => {
            await result.current.sendMessage('hello', null, 'profile-1');
        });

        expect(onWorkspaceAction).toHaveBeenCalledTimes(1);
        expect(result.current.turns).toHaveLength(1);
        expect(result.current.turns[0]).toMatchObject({
            agentId,
            children: [
                { kind: 'user_prompt', content: 'hello' },
                { kind: 'iteration', content: 'still delivered' },
            ],
        });
    });

    it('preserves queued agent activity when one dispatch fails', async () => {
        const agentId = 'root.test.1';
        const records = [
            {
                id: 'start-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'agent_started', agent_id: agentId,
                    agent_name: 'TEST', parent_agent_id: null,
                },
            },
            {
                id: 'user-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'user_message', content: 'hello', attachments: [] },
            },
            {
                id: 'content-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'content', content: 'partial', thinking: '' },
            },
            {
                id: 'spawn-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'spawn_requested', correlation_id: 'correlation-1' },
            },
            {
                id: 'iteration-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'iteration', content: 'complete', thinking: null,
                    tool_calls: [{ name: 'shell', arguments: { cmd: 'pwd' } }],
                },
            },
            {
                id: 'file-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'file_output', filename: 'report.md',
                    content_type: 'text/markdown', path: '/tmp/report.md',
                },
            },
            {
                id: 'compact-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: {
                    type: 'compaction', summary_text: 'summary',
                    user_intent_summary: 'intent', stats: { removed: 2 },
                },
            },
            {
                id: 'end-1', agent_id: agentId, agent_name: 'TEST', depth: 0,
                payload: { type: 'turn_end' },
            },
        ];
        const bytes = encoder.encode(`${records.map(JSON.stringify).join('\n')}\n`);
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromBytes(bytes, [43, 109, 211]),
        });
        const onAgentAction = vi.fn((action) => {
            if (action.type === 'APPEND_STREAM_CHUNK') {
                throw new Error('activity unavailable');
            }
        });
        const { result } = renderHook(() => useStreamingChat({ onAgentAction }));

        await act(async () => {
            await result.current.sendMessage('hello', null, 'profile-1');
        });

        const actionNames = onAgentAction.mock.calls.map(([action]) => (
            action.type === 'APPEND_ACTIVITY' ? action.entry.type : action.type
        ));
        expect(actionNames).toEqual([
            'AGENT_STARTED',
            'APPEND_STREAM_CHUNK',
            'spawn_requested',
            'tool_call',
            'file_output',
            'compaction',
        ]);
        expect(result.current.turns[0].children).toEqual(expect.arrayContaining([
            expect.objectContaining({ kind: 'iteration', content: 'complete' }),
            expect.objectContaining({ kind: 'file_output', filename: 'report.md' }),
        ]));
    });
});
