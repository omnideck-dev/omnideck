/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Validate the complete message before allowing it to change activity state.
 * @param {string} data
 * @returns {import('../catalog/activityTypes').RunActivityMessage}
 */
export function decodeActivityMessage(data) {
    /** @type {unknown} */
    const value = JSON.parse(data);
    if (!isRecord(value)
        || (value.type !== 'snapshot' && value.type !== 'started' && value.type !== 'finished')
        || !Array.isArray(value.runs)) {
        throw new Error('Invalid conversation activity message');
    }
    const runs = value.runs.map((run) => {
        if (!isRecord(run)
            || typeof run.conversation_id !== 'string' || !run.conversation_id
            || typeof run.run_id !== 'string' || !run.run_id) {
            throw new Error('Invalid conversation activity run');
        }
        return { conversation_id: run.conversation_id, run_id: run.run_id };
    });
    return { type: value.type, runs };
}

/**
 * Native EventSource owns reconnection; each new connection begins with a snapshot.
 * @param {(message: import('../catalog/activityTypes').RunActivityMessage) => void} onMessage
 * @returns {() => void}
 */
export function subscribeConversationActivity(onMessage) {
    const source = new EventSource('/api/chat/activity');
    source.onmessage = ({ data }) => {
        let message;
        try {
            message = decodeActivityMessage(data);
        } catch (error) {
            console.error('Rejected conversation activity message', error);
            return;
        }
        onMessage(message);
    };
    return () => source.close();
}
