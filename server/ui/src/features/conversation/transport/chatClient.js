/**
 * Build the wire request for one streamed conversation turn.
 *
 * Attachments may carry a browser-local preview used by the composer. That
 * value is not part of the backend contract and must not cross the transport
 * boundary.
 */
function buildTurnRequest(message, attachments, profileId, conversationId) {
    const body = { message: message || '(uploaded file)' };
    if (conversationId) body.conversation_id = conversationId;
    if (attachments?.length) {
        body.data = attachments.map(({ preview: _preview, ...rest }) => rest);
    }
    if (profileId) body.profile_id = profileId;
    return body;
}

/**
 * Start one conversation turn and yield the raw JSONL stream envelopes.
 *
 * This module owns only the wire protocol. Consumers decide how envelopes are
 * normalized and applied to frontend state. Records are yielded in arrival
 * order; blank and malformed complete lines are ignored, matching the existing
 * stream behavior.
 */
export async function* streamChatTurn({
    message,
    attachments,
    profileId,
    conversationId,
    signal,
}) {
    const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildTurnRequest(
            message,
            attachments,
            profileId,
            conversationId,
        )),
        signal,
    });
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
