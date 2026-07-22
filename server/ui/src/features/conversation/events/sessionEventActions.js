import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isRootAgentEvent,
} from './eventTypes.js';

// Records retained by the open frontend session so it can build Turns. This
// is a UI policy, not the backend's separate durability policy.
/** @type {Set<import('./conversationEvents.generated').ConversationEvent['type']>} */
const RETAINED_SESSION_EVENT_TYPES = new Set([
    EVENT.AGENT_STARTED,
    EVENT.AGENT_COMPLETED,
    EVENT.USER_MESSAGE,
    EVENT.ITERATION,
    EVENT.TOOL_RESULT,
    EVENT.COMPACTION,
    EVENT.FILE_OUTPUT,
    EVENT.SPAWN_REQUESTED,
    EVENT.ERROR,
]);

/**
 * Convert a canonical event into open-session reducer actions.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {Array<import('./frontendTypes').SessionAction>}
 */
export function getSessionEventActions(event) {
    /** @type {Array<import('./frontendTypes').SessionAction>} */
    const actions = [];
    if (!event?.type) return actions;

    if (RETAINED_SESSION_EVENT_TYPES.has(event.type)) {
        actions.push({ type: 'RETAIN_EVENT', event });
    }

    switch (event.type) {
        case EVENT.USER_MESSAGE:
            actions.push({ type: 'CONFIRM_USER_MESSAGE' });
            break;
        case EVENT.ITERATION:
            actions.push({ type: 'FINALIZE_ITERATION' });
            break;
        case EVENT.CONTENT:
            if (event.agent_id) actions.push({ type: 'UPDATE_IN_PROGRESS_ITERATION', event });
            break;
        case EVENT.AGENT_STARTED:
            if (event.agent_id && isRootAgentEvent(event)) {
                actions.push({ type: 'SET_ROOT_AGENT', agentId: event.agent_id });
            }
            break;
        case EVENT.TURN_END:
            actions.push({ type: 'FINISH_TURN' });
            break;
        default:
            break;
    }
    return actions;
}
