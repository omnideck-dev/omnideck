import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    ChatStreamHttpError,
    streamAgentRun,
    removeQueuedTurn,
    streamChatTurn,
} from '../chatClient.js';

const encoder = new TextEncoder();

function bodyFromChunks(chunks) {
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

function bodyThatFails(error) {
    return {
        getReader: () => ({
            read: async () => { throw error; },
        }),
    };
}

async function collect(stream) {
    const records = [];
    for await (const record of stream) records.push(record);
    return records;
}

describe('streamChatTurn', () => {
    afterEach(() => vi.restoreAllMocks());

    it('posts the turn request and removes UI-only attachment previews', async () => {
        const signal = new AbortController().signal;
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, body: null });
        const attachments = [{
            filename: 'diagram.png',
            content_type: 'image/png',
            base64: 'aW1hZ2U=',
            preview: 'blob:local-preview',
        }];

        await collect(streamChatTurn({
            request: { kind: 'message', message: '', attachments, profileId: 'profile-1' },
            conversationId: 'conversation-1',
            signal,
        }));

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        const [url, init] = fetchSpy.mock.calls[0];
        expect(url).toBe('/api/chat');
        expect(init).toMatchObject({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal,
        });
        expect(JSON.parse(init.body)).toEqual({
            message: '(uploaded file)',
            conversation_id: 'conversation-1',
            profile_id: 'profile-1',
            data: [{
                filename: 'diagram.png',
                content_type: 'image/png',
                base64: 'aW1hZ2U=',
            }],
        });
    });

    it('yields the queued reply when the agent is already working', async () => {
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            status: 202,
            json: async () => ({ nudge: { id: 'n1', run_id: 'run-1' } }),
        });

        const records = await collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } }));

        expect(records).toEqual([{ nudge: { id: 'n1', run_id: 'run-1' } }]);
    });

    it('posts goal answers to the conversation answers route', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, body: null });
        const answers = [{ question_id: 'day', question_revision: 1, question: 'Which day?', answer: 'Tuesday' }];

        await collect(streamChatTurn({
            request: { kind: 'answers', goalId: 'g1', answers, profileId: 'p1' },
            conversationId: 'conversation-1',
        }));

        const [url, init] = fetchSpy.mock.calls[0];
        expect(url).toBe('/api/conversations/sessions/conversation-1/goal/answers');
        expect(JSON.parse(init.body)).toEqual({
            goal_id: 'g1', answers: [{ question_id: 'day', question_revision: 1, answer: 'Tuesday' }], profile_id: 'p1',
        });
    });

    it('omits optional request fields when they are not supplied', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, body: null });

        await collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } }));

        const [, init] = fetchSpy.mock.calls[0];
        expect(JSON.parse(init.body)).toEqual({ message: 'hello' });
    });

    it('decodes records split across arbitrary UTF-8 byte boundaries', async () => {
        const expected = {
            agent_id: 'root.test.1',
            payload: { type: 'content', content: 'café 🚀' },
        };
        const bytes = encoder.encode(`${JSON.stringify(expected)}\n`);
        const oneByteChunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromChunks(oneByteChunks),
        });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .resolves.toEqual([expected]);
    });

    it('preserves order for multiple records and ignores blank lines', async () => {
        const first = { payload: { type: 'agent_started' } };
        const second = { payload: { type: 'turn_end' } };
        const jsonl = `  \n${JSON.stringify(first)}\n\n${JSON.stringify(second)}\n`;
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromChunks([encoder.encode(jsonl)]),
        });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .resolves.toEqual([first, second]);
    });

    it('ignores malformed complete lines and continues with later records', async () => {
        const first = { payload: { type: 'content', content: 'one' } };
        const second = { payload: { type: 'content', content: 'two' } };
        const jsonl = [JSON.stringify(first), '{not-json}', JSON.stringify(second), ''].join('\n');
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromChunks([encoder.encode(jsonl)]),
        });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .resolves.toEqual([first, second]);
    });

    it('does not emit an unterminated trailing record', async () => {
        const record = { payload: { type: 'turn_end' } };
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromChunks([encoder.encode(JSON.stringify(record))]),
        });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .resolves.toEqual([]);
    });

    it('completes without records when the response has no body', async () => {
        vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, body: null });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .resolves.toEqual([]);
    });

    it('propagates fetch failures', async () => {
        const error = new TypeError('network unavailable');
        vi.spyOn(global, 'fetch').mockRejectedValue(error);

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .rejects.toBe(error);
    });

    it('propagates reader failures', async () => {
        const error = new Error('stream disconnected');
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyThatFails(error),
        });

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .rejects.toBe(error);
    });

    it('propagates abort failures', async () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        vi.spyOn(global, 'fetch').mockRejectedValue(error);

        await expect(collect(streamChatTurn({ request: { kind: 'message', message: 'hello' } })))
            .rejects.toBe(error);
    });

    it('follows an active run after the supplied cursor', async () => {
        const event = {
            run_id: 'run/one',
            seq: 19,
            payload: { type: 'turn_end' },
        };
        const signal = new AbortController().signal;
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: true,
            body: bodyFromChunks([encoder.encode(`${JSON.stringify(event)}\n`)]),
        });

        await expect(collect(streamAgentRun({
            runId: 'run/one',
            afterSeq: 18,
            signal,
        }))).resolves.toEqual([event]);
        expect(fetchSpy).toHaveBeenCalledWith(
            '/api/chat/runs/run%2Fone/events?after=18',
            { signal },
        );
    });

    it('throws a typed HTTP error with the backend message', async () => {
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: false,
            status: 404,
            json: async () => ({ error: 'Active run not found.' }),
        });

        await expect(collect(streamAgentRun({
            runId: 'missing',
            afterSeq: 3,
        }))).rejects.toEqual(expect.objectContaining({
            name: 'ChatStreamHttpError',
            status: 404,
            message: 'Active run not found.',
        }));
        await expect(collect(streamAgentRun({
            runId: 'missing',
            afterSeq: 3,
        }))).rejects.toBeInstanceOf(ChatStreamHttpError);
    });
});

describe('removeQueuedTurn', () => {
    afterEach(() => vi.restoreAllMocks());

    it('deletes the queued message for the conversation', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });

        await expect(removeQueuedTurn({ nudgeId: 'n1', conversationId: 'c1' })).resolves.toEqual({ ok: true });

        expect(fetchSpy).toHaveBeenCalledWith('/api/chat/nudges/n1?conversation_id=c1', { method: 'DELETE' });
    });

    it('reports a message the agent already read', async () => {
        vi.spyOn(global, 'fetch').mockResolvedValue({
            ok: false,
            status: 409,
            json: async () => ({ error: 'The agent already read this message.' }),
        });

        await expect(removeQueuedTurn({ nudgeId: 'n1', conversationId: 'c1' })).resolves.toEqual({
            ok: false,
            status: 409,
            error: 'The agent already read this message.',
        });
    });
});
