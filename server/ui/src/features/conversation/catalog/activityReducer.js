import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';

/**
 * @typedef {{
 *   running: Map<string, string>,
 *   finished: Set<string>,
 *   visibleConversationId: string | null,
 * }} ConversationActivityState
 * @typedef {{ type: 'runs/snapshot' | 'runs/started' | 'runs/finished', runs: import('../../app/appEffects.types').RunIdentity[] }
 *   | { type: 'visibility', conversationId: string | null }} ConversationActivityAction
 */

/** @type {ConversationActivityState} */
export const initialActivityState = {
    running: new Map(), finished: new Set(), visibleConversationId: null,
};

/**
 * @param {ConversationActivityState} state
 * @param {ConversationActivityAction} event
 * @returns {ConversationActivityState}
 */
export function activityReducer(state, event) {
    const running = new Map(state.running);
    const finished = new Set(state.finished);
    if (event.type === 'visibility') {
        if (state.visibleConversationId === event.conversationId) return state;
        if (event.conversationId !== null) finished.delete(event.conversationId);
        return { running, finished, visibleConversationId: event.conversationId };
    }
    if (event.type === APP_EFFECT_TYPES.RUNS_SNAPSHOT) {
        const active = new Map(event.runs.map((run) => [run.conversationId, run.runId]));
        for (const [conversationId, runId] of running) {
            if (active.get(conversationId) !== runId && conversationId !== state.visibleConversationId) {
                finished.add(conversationId);
            }
        }
        for (const conversationId of active.keys()) finished.delete(conversationId);
        return { ...state, running: active, finished };
    }
    for (const run of event.runs) {
        const id = run.conversationId;
        if (event.type === APP_EFFECT_TYPES.RUNS_STARTED) {
            running.set(id, run.runId);
            finished.delete(id);
        } else if (event.type === APP_EFFECT_TYPES.RUNS_FINISHED && running.get(id) === run.runId) {
            running.delete(id);
            if (id !== state.visibleConversationId) finished.add(id);
        }
    }
    return { ...state, running, finished };
}
