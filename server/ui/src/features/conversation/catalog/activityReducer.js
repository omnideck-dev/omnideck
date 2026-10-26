/** @type {import('./activityTypes').ConversationActivityState} */
export const initialActivityState = {
    running: new Map(), finished: new Set(), visibleConversationId: null,
};

/**
 * @param {import('./activityTypes').ConversationActivityState} state
 * @param {import('./activityTypes').ConversationActivityAction} event
 * @returns {import('./activityTypes').ConversationActivityState}
 */
export function activityReducer(state, event) {
    const running = new Map(state.running);
    const finished = new Set(state.finished);
    if (event.type === 'visibility') {
        if (state.visibleConversationId === event.conversationId) return state;
        if (event.conversationId !== null) finished.delete(event.conversationId);
        return { running, finished, visibleConversationId: event.conversationId };
    }
    if (event.type === 'snapshot') {
        const active = new Map(event.runs.map((run) => [run.conversation_id, run.run_id]));
        for (const [conversationId, runId] of running) {
            if (active.get(conversationId) !== runId && conversationId !== state.visibleConversationId) {
                finished.add(conversationId);
            }
        }
        for (const conversationId of active.keys()) finished.delete(conversationId);
        return { ...state, running: active, finished };
    }
    for (const run of event.runs) {
        const id = run.conversation_id;
        if (event.type === 'started') {
            running.set(id, run.run_id);
            finished.delete(id);
        } else if (event.type === 'finished' && running.get(id) === run.run_id) {
            running.delete(id);
            if (id !== state.visibleConversationId) finished.add(id);
        }
    }
    return { ...state, running, finished };
}
