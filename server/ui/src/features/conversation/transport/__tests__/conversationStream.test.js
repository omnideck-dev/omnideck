import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamConversationTurn } from '../conversationStream.js';

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

describe('streamConversationTurn', () => {
    afterEach(() => vi.restoreAllMocks());

    it('posts the turn request and removes UI-only attachment previews', async () => {
        const signal = new AbortController().signal;
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ body: null });
        const attachments = [{
            filename: 'diagram.png',
            content_type: 'image/png',
            base64: 'aW1hZ2U=',
            preview: 'blob:local-preview',
        }];

        await collect(streamConversationTurn({
            message: '',
            attachments,
            profileId: 'profile-1',
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

    it('omits optional request fields when they are not supplied', async () => {
        const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({ body: null });

        await collect(streamConversationTurn({ message: 'hello' }));

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
            body: bodyFromChunks(oneByteChunks),
        });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .resolves.toEqual([expected]);
    });

    it('preserves order for multiple records and ignores blank lines', async () => {
        const first = { payload: { type: 'agent_started' } };
        const second = { payload: { type: 'turn_end' } };
        const jsonl = `  \n${JSON.stringify(first)}\n\n${JSON.stringify(second)}\n`;
        vi.spyOn(global, 'fetch').mockResolvedValue({
            body: bodyFromChunks([encoder.encode(jsonl)]),
        });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .resolves.toEqual([first, second]);
    });

    it('ignores malformed complete lines and continues with later records', async () => {
        const first = { payload: { type: 'content', content: 'one' } };
        const second = { payload: { type: 'content', content: 'two' } };
        const jsonl = [JSON.stringify(first), '{not-json}', JSON.stringify(second), ''].join('\n');
        vi.spyOn(global, 'fetch').mockResolvedValue({
            body: bodyFromChunks([encoder.encode(jsonl)]),
        });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .resolves.toEqual([first, second]);
    });

    it('does not emit an unterminated trailing record', async () => {
        const record = { payload: { type: 'turn_end' } };
        vi.spyOn(global, 'fetch').mockResolvedValue({
            body: bodyFromChunks([encoder.encode(JSON.stringify(record))]),
        });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .resolves.toEqual([]);
    });

    it('completes without records when the response has no body', async () => {
        vi.spyOn(global, 'fetch').mockResolvedValue({ body: null });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .resolves.toEqual([]);
    });

    it('propagates fetch failures', async () => {
        const error = new TypeError('network unavailable');
        vi.spyOn(global, 'fetch').mockRejectedValue(error);

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .rejects.toBe(error);
    });

    it('propagates reader failures', async () => {
        const error = new Error('stream disconnected');
        vi.spyOn(global, 'fetch').mockResolvedValue({ body: bodyThatFails(error) });

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .rejects.toBe(error);
    });

    it('propagates abort failures', async () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        vi.spyOn(global, 'fetch').mockRejectedValue(error);

        await expect(collect(streamConversationTurn({ message: 'hello' })))
            .rejects.toBe(error);
    });
});
