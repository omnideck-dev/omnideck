import { describe, expect, it } from 'vitest';
import { projectAgentActivity } from '../projectAgentActivity.js';

describe('projectAgentActivity', () => {
    it('projects one root agent activity rail from its transcript turn', () => {
        const turns = [{
            id: 'turn-1',
            agentId: 'root-1',
            children: [
                { kind: 'user_prompt', id: 'user-1', content: 'hello' },
                {
                    kind: 'iteration',
                    id: 'iteration-1',
                    thinking: 'reasoning',
                    content: 'answer',
                    toolCalls: [{ name: 'shell', arguments: { cmd: 'pwd' } }],
                },
                {
                    kind: 'file_output',
                    id: 'file-1',
                    filename: 'report.md',
                    contentType: 'text/markdown',
                    path: '/tmp/report.md',
                },
                {
                    kind: 'spawn_requested',
                    id: 'spawn-1',
                    correlationId: 'correlation-1',
                },
            ],
        }];

        expect(projectAgentActivity(turns, 'root-1')).toEqual([
            { type: 'thinking', thinking: 'reasoning' },
            { type: 'content', content: 'answer' },
            { type: 'tool_call', name: 'shell', arguments: { cmd: 'pwd' } },
            {
                type: 'file_output',
                filename: 'report.md',
                content_type: 'text/markdown',
                path: '/tmp/report.md',
                timestamp: undefined,
            },
            { type: 'spawn_requested', correlationId: 'correlation-1' },
        ]);
    });

    it('does not mix activity from different root turns', () => {
        const turns = [
            {
                id: 'turn-1',
                agentId: 'root-1',
                children: [{ kind: 'iteration', content: 'first', toolCalls: [] }],
            },
            {
                id: 'turn-2',
                agentId: 'root-2',
                children: [{ kind: 'iteration', content: 'second', toolCalls: [] }],
            },
        ];

        expect(projectAgentActivity(turns, 'root-2')).toEqual([
            { type: 'content', content: 'second' },
        ]);
    });
});
