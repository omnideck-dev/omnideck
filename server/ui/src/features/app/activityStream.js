import { APP_EFFECT_TYPES } from './appEffectTypes.js';

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * @param {unknown} runs
 * @returns {import('./activityMessages.generated').RunIdentity[]}
 */
function decodeRuns(runs) {
    if (!Array.isArray(runs)) throw new Error('Invalid activity runs');
    return runs.map((run) => {
        if (!isRecord(run)
            || typeof run.conversation_id !== 'string' || !run.conversation_id
            || typeof run.run_id !== 'string' || !run.run_id) {
            throw new Error('Invalid activity run');
        }
        return { conversation_id: run.conversation_id, run_id: run.run_id };
    });
}

/**
 * @param {unknown} goal
 * @returns {import('./activityMessages.generated').Goal}
 */
function decodeGoal(goal) {
    if (!isRecord(goal) || typeof goal.id !== 'string' || typeof goal.conversation_id !== 'string'
        || typeof goal.revision !== 'number' || !isRecord(goal.next)) {
        throw new Error('Invalid activity goal');
    }
    return /** @type {import('./activityMessages.generated').Goal} */ (/** @type {unknown} */ (goal));
}

/**
 * @param {unknown} conversation
 * @returns {import('./activityMessages.generated').ConversationSummary}
 */
function decodeConversation(conversation) {
    if (!isRecord(conversation) || typeof conversation.conversation_id !== 'string' || !conversation.conversation_id) {
        throw new Error('Invalid activity conversation');
    }
    return /** @type {import('./activityMessages.generated').ConversationSummary} */ (/** @type {unknown} */ (conversation));
}

/**
 * @param {string} data
 * @returns {import('./activityMessages.generated').ActivityMessage}
 */
export function decodeActivityMessage(data) {
    /** @type {unknown} */
    const value = JSON.parse(data);
    if (!isRecord(value)) throw new Error('Invalid activity message');
    if (value.type === 'run_snapshot' || value.type === 'run_started' || value.type === 'run_finished') {
        return { type: value.type, runs: decodeRuns(value.runs) };
    }
    if (value.type === 'goal_snapshot') {
        if (!Array.isArray(value.goals)) throw new Error('Invalid goal snapshot');
        return { type: 'goal_snapshot', goals: value.goals.map(decodeGoal) };
    }
    if (value.type === 'goal_changed') {
        if (typeof value.conversation_id !== 'string') throw new Error('Invalid goal change');
        return { type: 'goal_changed', conversation_id: value.conversation_id, goal: decodeGoal(value.goal) };
    }
    if (value.type === 'conversation_resync') return { type: 'conversation_resync' };
    if (value.type === 'conversation_changed') {
        if (typeof value.archived !== 'boolean') throw new Error('Invalid conversation change');
        return {
            type: 'conversation_changed',
            conversation: decodeConversation(value.conversation),
            archived: value.archived,
        };
    }
    if (value.type === 'conversation_removed') {
        if (typeof value.conversation_id !== 'string' || !value.conversation_id) {
            throw new Error('Invalid conversation removal');
        }
        return { type: 'conversation_removed', conversation_id: value.conversation_id };
    }
    throw new Error('Unknown activity message');
}

/** @param {import('./activityMessages.generated').RunIdentity[]} runs */
function runPayload(runs) {
    return { runs: runs.map((run) => ({ conversationId: run.conversation_id, runId: run.run_id })) };
}

/**
 * @param {import('./activityMessages.generated').ActivityMessage} message
 * @returns {import('./appEffects.types').AppEffect}
 */
export function activityEffect(message) {
    switch (message.type) {
    case 'run_snapshot': return { type: APP_EFFECT_TYPES.RUNS_SNAPSHOT, payload: runPayload(message.runs) };
    case 'run_started': return { type: APP_EFFECT_TYPES.RUNS_STARTED, payload: runPayload(message.runs) };
    case 'run_finished': return { type: APP_EFFECT_TYPES.RUNS_FINISHED, payload: runPayload(message.runs) };
    case 'goal_snapshot': return { type: APP_EFFECT_TYPES.GOALS_SNAPSHOT, payload: { goals: message.goals } };
    case 'conversation_resync': return { type: APP_EFFECT_TYPES.CONVERSATIONS_RESYNC, payload: null };
    case 'conversation_changed': return {
        type: APP_EFFECT_TYPES.CONVERSATIONS_CHANGED,
        payload: { conversation: message.conversation, archived: message.archived },
    };
    case 'conversation_removed': return {
        type: APP_EFFECT_TYPES.CONVERSATIONS_REMOVED,
        payload: { conversationId: message.conversation_id },
    };
    default: return {
        type: APP_EFFECT_TYPES.GOALS_CHANGED,
        payload: { conversationId: message.conversation_id, goal: message.goal },
    };
    }
}

/**
 * @param {(effect: import('./appEffects.types').AppEffect) => void} dispatch
 * @returns {() => void}
 */
export function subscribeActivityStream(dispatch) {
    /** @type {EventSource} */
    let source;
    const open = () => {
        source = new EventSource('/api/chat/activity');
        source.onmessage = ({ data }) => {
            let message;
            try {
                message = decodeActivityMessage(data);
            } catch (error) {
                console.error('Rejected activity message', error);
                return;
            }
            dispatch(activityEffect(message));
        };
    };
    const reopenIfClosed = () => {
        if (document.visibilityState !== 'visible' || source.readyState !== EventSource.CLOSED) return;
        open();
    };
    open();
    document.addEventListener('visibilitychange', reopenIfClosed);
    window.addEventListener('online', reopenIfClosed);
    return () => {
        document.removeEventListener('visibilitychange', reopenIfClosed);
        window.removeEventListener('online', reopenIfClosed);
        source.close();
    };
}
