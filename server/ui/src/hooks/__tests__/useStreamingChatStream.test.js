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
        const onAgentEvent = vi.fn();
        const { result } = renderHook(() => useStreamingChat({ onAgentEvent }));

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
        expect(onAgentEvent).toHaveBeenCalledTimes(1);
    });
});
