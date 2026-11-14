import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import useConversationSessionController from '../useConversationSessionController.js';

const encoder = new TextEncoder();

/** A streamed response whose records the test pushes one batch at a time. */
function liveStream() {
    const waiting = [];
    const chunks = [];
    let closed = false;
    const settle = () => {
        while (waiting.length && (chunks.length || closed)) {
            const resolve = waiting.shift();
            resolve(chunks.length ? { done: false, value: chunks.shift() } : { done: true, value: undefined });
        }
    };
    return {
        response: {
            ok: true,
            status: 200,
            body: { getReader: () => ({ read: () => new Promise((resolve) => { waiting.push(resolve); settle(); }) }) },
        },
        push(records) {
            chunks.push(encoder.encode(`${records.map((record) => JSON.stringify(record)).join('\n')}\n`));
            settle();
        },
        close() {
            closed = true;
            settle();
        },
    };
}

let seq = 0;
function envelope(id, payload) {
    seq += 1;
    return { run_id: 'run-1', seq, id, agent_id: 'root-1', agent_name: 'Root', depth: 0, payload };
}

function queuedReply() {
    return { ok: true, status: 202, json: async () => ({ nudge: { id: 'n1', run_id: 'run-1' } }) };
}

const answerContext = {
    type: 'goal_question', goal_id: 'g1', question_id: 'day', question_revision: 1, question: 'Which day?', answer: 'Tuesday',
};

afterEach(() => {
    vi.restoreAllMocks();
    seq = 0;
});

async function flush() {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
    });
}

it('follows the run after a 202 and builds the queue from its events', async () => {
    const run = liveStream();
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url) => {
        if (url === '/api/chat') return Promise.resolve(queuedReply());
        if (url === '/api/chat/runs/run-1/events?after=0') return Promise.resolve(run.response);
        throw new Error(`Unexpected request: ${url}`);
    });
    const { result } = renderHook(() => useConversationSessionController());
    let sending;
    await act(async () => {
        sending = result.current.sendMessage('Also check Thursday', null, 'profile-1');
    });
    await flush();

    // The message waits in the queue, not as an optimistic chat turn.
    expect(result.current.turns).toEqual([]);
    run.push([
        envelope('start', { type: 'agent_started', agent_id: 'root-1', agent_name: 'Root', parent_agent_id: null }),
        envelope('q1', { type: 'nudge_queued', nudge_id: 'n1', content: 'Also check Thursday', context: [] }),
        envelope('q2', { type: 'nudge_queued', nudge_id: 'n2', content: 'And Friday', context: [] }),
        envelope('q3', { type: 'nudge_queued', nudge_id: 'n3', content: '', context: [answerContext] }),
    ]);
    await flush();
    expect(result.current.queue.map((item) => item.id)).toEqual(['n1', 'n2', 'n3']);
    expect(result.current.isStreaming).toBe(true);

    run.push([
        envelope('u1', { type: 'user_message', content: 'Also check Thursday', attachments: [], context: [], is_nudge: true, nudge_id: 'n1' }),
        envelope('r2', { type: 'nudge_removed', nudge_id: 'n2', reason: 'removed' }),
    ]);
    await flush();
    expect(result.current.queue.map((item) => item.id)).toEqual(['n3']);
    expect(result.current.returned).toEqual([]);

    run.push([
        envelope('r3', { type: 'nudge_removed', nudge_id: 'n3', reason: 'returned' }),
        envelope('end', { type: 'turn_end' }),
    ]);
    run.close();
    await act(async () => { await sending; });

    expect(result.current.queue).toEqual([]);
    expect(result.current.returned).toEqual([{ id: 'n3', content: '', context: [answerContext] }]);
    act(() => result.current.consumeReturnedMessages(['n3']));
    expect(result.current.returned).toEqual([]);
    expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual(['/api/chat', '/api/chat/runs/run-1/events?after=0']);
});

it('posts a message while the agent works and keeps the one run connection', async () => {
    const run = liveStream();
    const requests = [];
    vi.spyOn(global, 'fetch').mockImplementation((url, init) => {
        requests.push([url, init?.method]);
        if (url === '/api/chat' && requests.length === 1) return Promise.resolve(run.response);
        if (url === '/api/chat') return Promise.resolve(queuedReply());
        throw new Error(`Unexpected request: ${url}`);
    });
    const { result } = renderHook(() => useConversationSessionController());
    let first;
    await act(async () => {
        first = result.current.sendMessage('hello', null, 'profile-1');
    });
    run.push([envelope('start', { type: 'agent_started', agent_id: 'root-1', agent_name: 'Root', parent_agent_id: null })]);
    await flush();

    let queued;
    await act(async () => {
        queued = await result.current.sendMessage('Also check Thursday', null, 'profile-1');
    });
    expect(queued).toEqual({ ok: true, queued: true });
    expect(requests).toEqual([['/api/chat', 'POST'], ['/api/chat', 'POST']]);

    // Files cannot wait in the queue.
    let withFiles;
    await act(async () => {
        withFiles = await result.current.sendMessage('notes', [{ filename: 'a.txt', content_type: 'text/plain', base64: 'YQ==' }]);
    });
    expect(withFiles).toMatchObject({ ok: false, status: 409 });
    expect(requests).toHaveLength(2);

    run.push([envelope('end', { type: 'turn_end' })]);
    run.close();
    await act(async () => { await first; });
});

it('sends goal answers to the answers route', async () => {
    const run = liveStream();
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(run.response);
    const { result } = renderHook(() => useConversationSessionController());
    const conversationId = result.current.activeConversationId;
    const answers = [{ question_id: 'day', question_revision: 1, question: 'Which day?', answer: 'Tuesday' }];
    let sending;
    await act(async () => {
        sending = result.current.sendAnswers('g1', answers);
    });

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe(`/api/conversations/sessions/${conversationId}/goal/answers`);
    expect(JSON.parse(init.body)).toEqual({ goal_id: 'g1', answers: [{ question_id: 'day', question_revision: 1, answer: 'Tuesday' }] });
    run.push([envelope('end', { type: 'turn_end' })]);
    run.close();
    await act(async () => { await sending; });
});

it('removes a queued message on the server and from the queue', async () => {
    const run = liveStream();
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((url, init) => {
        if (init?.method === 'DELETE') return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
        return Promise.resolve(run.response);
    });
    const { result } = renderHook(() => useConversationSessionController());
    const conversationId = result.current.activeConversationId;
    let sending;
    await act(async () => {
        sending = result.current.sendMessage('hello', null, 'profile-1');
    });
    run.push([envelope('q1', { type: 'nudge_queued', nudge_id: 'n1', content: 'Later', context: [] })]);
    await flush();
    expect(result.current.queue).toHaveLength(1);

    let removed;
    await act(async () => {
        removed = await result.current.removeQueuedMessage('n1');
    });

    expect(removed).toEqual({ ok: true });
    expect(fetchSpy).toHaveBeenCalledWith(`/api/chat/nudges/n1?conversation_id=${conversationId}`, { method: 'DELETE' });
    expect(result.current.queue).toEqual([]);
    expect(result.current.returned).toEqual([]);
    run.push([envelope('end', { type: 'turn_end' })]);
    run.close();
    await act(async () => { await sending; });
});
