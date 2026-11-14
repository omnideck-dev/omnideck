/**
 * Build the URL and body for one user turn: a message from the composer or
 * answers from the goal question card.
 *
 * Attachments may carry a browser-local preview used by the composer. That
 * value is not part of the backend contract and must not cross the transport
 * boundary.
 */
function buildTurnRequest(request, conversationId) {
    if (request.kind === 'answers') {
        return {
            url: `/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal/answers`,
            body: {
                goal_id: request.goalId,
                // The question text is for the optimistic chat turn only.
                answers: request.answers.map(({ question_id, question_revision, answer }) => ({
                    question_id, question_revision, answer,
                })),
                ...(request.profileId ? { profile_id: request.profileId } : {}),
            },
        };
    }
    const { message, attachments, profileId } = request;
    const body = { message: message || '(uploaded file)' };
    if (conversationId) body.conversation_id = conversationId;
    if (attachments?.length) {
        body.data = attachments.map(({ preview: _preview, ...rest }) => rest);
    }
    if (profileId) body.profile_id = profileId;
    return { url: '/api/chat', body };
}

/** HTTP failure from either the initial stream or a resumed run stream. */
export class ChatStreamHttpError extends Error {
    constructor(status, message) {
        super(message || `Conversation stream failed with status ${status}`);
        this.name = 'ChatStreamHttpError';
        this.status = status;
    }
}

async function throwIfResponseFailed(response) {
    if (response.ok) return;
    let message = null;
    try {
        const body = await response.json();
        message = body?.error;
    } catch {
        // The status fallback below is enough when an intermediary returns
        // HTML or an empty error body.
    }
    throw new ChatStreamHttpError(response.status, message);
}

async function* streamJsonLines(response) {
    await throwIfResponseFailed(response);
    if (!response.body) return;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let newlineIndex;
        while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
            const line = buffer.slice(0, newlineIndex).trim();
            buffer = buffer.slice(newlineIndex + 1);
            if (!line) continue;

            try {
                yield JSON.parse(line);
            } catch {
                // Ignore a malformed complete record and continue the stream.
            }
        }
    }
}

/**
 * Send one user turn. The server either starts a run and streams it, or,
 * while the agent works, queues the turn and replies 202 with
 * `{nudge: {id, run_id}}`.
 */
export async function openChatTurn({ request, conversationId, signal }) {
    const { url, body } = buildTurnRequest(request, conversationId);
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
    });
}

/** Read the queued-message reply, or null when the server started a run. */
export async function readQueuedReply(response) {
    if (response.status !== 202) return null;
    const body = await response.json().catch(() => ({}));
    return body?.nudge || {};
}

/**
 * Start one conversation turn and yield the raw JSONL stream envelopes.
 *
 * This module owns only the wire protocol. Consumers decide how envelopes are
 * normalized and applied to frontend state. Records are yielded in arrival
 * order; blank and malformed complete lines are ignored, matching the existing
 * stream behavior. A queued turn yields one `{nudge}` record and ends.
 */
export async function* streamChatTurn({ request, conversationId, signal }) {
    const response = await openChatTurn({ request, conversationId, signal });
    const nudge = await readQueuedReply(response);
    if (nudge) {
        yield { nudge };
        return;
    }
    yield* streamJsonLines(response);
}

/** Remove a queued message before the agent reads it. */
export async function removeQueuedTurn({ nudgeId, conversationId }) {
    const response = await fetch(
        `/api/chat/nudges/${encodeURIComponent(nudgeId)}?conversation_id=${encodeURIComponent(conversationId)}`,
        { method: 'DELETE' },
    );
    if (response.ok) return { ok: true };
    const body = await response.json().catch(() => ({}));
    return { ok: false, status: response.status, error: body?.error };
}

/** Replay records after a processed sequence, then follow the active run. */
export async function* streamAgentRun({ runId, afterSeq, signal }) {
    const response = await fetch(
        `/api/chat/runs/${encodeURIComponent(runId)}/events?after=${afterSeq}`,
        { signal },
    );
    yield* streamJsonLines(response);
}
